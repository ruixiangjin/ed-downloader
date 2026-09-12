from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Coroutine
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Any

import typer
from rich.console import Console
from rich.table import Table

from monash_ed_downloader.auth import (
    clear_login_confirmation,
    has_confirmed_login,
    interactive_login,
)
from monash_ed_downloader.cache import ResourceCache
from monash_ed_downloader.courses import CourseCatalog
from monash_ed_downloader.errors import EdDownloaderError, LoginRequiredError
from monash_ed_downloader.forum import sync_discussions
from monash_ed_downloader.lessons import lesson_catalog, sync_lessons
from monash_ed_downloader.models import Course, CourseStatus
from monash_ed_downloader.selection import parse_group_selection
from monash_ed_downloader.session import BrowserSession
from monash_ed_downloader.settings import Settings

app = typer.Typer(name="ed-downloader", no_args_is_help=True)
console = Console()


class SyncScope(StrEnum):
    ALL = "all"
    DISCUSSIONS = "discussions"
    LESSONS = "lessons"


def run[T](operation: Coroutine[Any, Any, T]) -> T:
    try:
        return asyncio.run(operation)
    except EdDownloaderError as error:
        console.print(f"[red]错误：[/red]{error}")
        raise typer.Exit(code=1) from error


async def _login(timeout: int) -> None:
    settings = Settings.default()
    console.print("正在打开 Chrome。请只在浏览器中完成 Ed 登录和学校 MFA。")
    await interactive_login(settings, timeout_seconds=timeout, notify=console.print)


async def _with_auto_login[T](operation: Callable[[], Awaitable[T]]) -> T:
    settings = Settings.default()
    if not has_confirmed_login(settings):
        console.print("首次配置或上次登录尚未成功，直接进入登录流程。")
        await _login(600)
    try:
        return await operation()
    except LoginRequiredError:
        clear_login_confirmation(settings)
        console.print("没有检测到有效 Ed 登录，进入浏览器登录流程。")
    await _login(600)
    return await operation()


@app.command()
def login(timeout: Annotated[int, typer.Option(min=30)] = 600) -> None:
    """Open Chrome for user-controlled Ed login."""
    run(_login(timeout))


@app.command()
def doctor() -> None:
    """Check local paths, Chrome, and the saved Ed session."""
    run(_doctor())


async def _doctor() -> None:
    settings = Settings.default()
    console.print("Python project: [green]ready[/green]")
    console.print(f"Default output: {settings.output_root}")
    console.print(f"Private state: {settings.state_root}")
    async with BrowserSession(settings, headless=True) as session:
        status = await session.status()
    colour = "green" if status.authenticated else "yellow"
    console.print(f"Ed session: [{colour}]{status.message}[/{colour}]")


def _course_table(title: str, courses_to_show: list[Course]) -> Table:
    table = Table(title=title)
    table.add_column("Code", style="cyan", no_wrap=True)
    table.add_column("Ed ID", justify="right")
    table.add_column("Course name")
    for course in courses_to_show:
        table.add_row(course.code, course.id, course.title)
    if not courses_to_show:
        table.add_row("—", "—", "No courses")
    return table


async def _load_courses(session: BrowserSession, settings: Settings) -> list[Course]:
    await session.ensure_authenticated()
    return await CourseCatalog(
        session.page, base_url=settings.ed_base_url, region=settings.region
    ).list_courses()


@app.command()
def courses() -> None:
    """List current and archived ED courses."""
    run(_with_auto_login(_courses))


async def _courses() -> None:
    settings = Settings.default()
    async with BrowserSession(settings, headless=True) as session:
        items = await _load_courses(session, settings)
    console.print(
        _course_table("Current courses", [c for c in items if c.status is CourseStatus.CURRENT])
    )
    archived_groups = list(
        dict.fromkeys(
            c.archive_group or "Archived" for c in items if c.status is CourseStatus.ARCHIVED
        )
    )
    for group in archived_groups:
        console.print(_course_table(group, [c for c in items if c.archive_group == group]))
    unclassified = [c for c in items if c.status is CourseStatus.UNCLASSIFIED]
    if unclassified:
        console.print(_course_table("Unclassified courses", unclassified))


@app.command()
def scan(
    course: Annotated[str, typer.Option("--course", "-c")],
) -> None:
    """Inspect a course and list its available Lesson groups without downloading files."""
    run(_with_auto_login(lambda: _scan(course)))


async def _scan(selector: str) -> None:
    settings = Settings.default()
    async with BrowserSession(settings, headless=True) as session:
        courses_to_show = await _load_courses(session, settings)
        course = CourseCatalog.resolve(courses_to_show, selector)
        catalog = await lesson_catalog(
            session.page,
            course,
            base_url=settings.ed_base_url,
            region=settings.region,
        )
    console.print(f"[bold]{course.code} — {course.title}[/bold]")
    console.print("Discussions: available")
    modules = catalog["modules"]
    if not catalog["lessons"]:
        console.print("Lessons: no downloadable Lessons found")
        return
    console.print(f"Lessons: {len(catalog['lessons'])}; groups: {len(modules)}")
    for index, group in enumerate(modules, 1):
        console.print(f"  [cyan]{index}[/cyan]  {group.get('name') or 'Ungrouped'}")


async def _sync_course(
    session: BrowserSession,
    settings: Settings,
    course: Course,
    *,
    scope: SyncScope,
    group_selection: str | None,
    force_full: bool,
    refresh: bool,
    output_root: Path,
) -> None:
    console.print(f"\n[bold]{course.code} — {course.title}[/bold]")
    if scope in {SyncScope.ALL, SyncScope.DISCUSSIONS}:
        path, stats = await sync_discussions(
            session.page,
            course,
            output_root,
            force_full=force_full,
            progress=lambda message: console.print(message, end="\r"),
        )
        console.print(
            f"Discussions：新增 {stats['new_threads']}；更新 {stats['updated_threads']}；"
            f"未变化 {stats['unchanged_threads']}。"
        )
        console.print(f"论坛 JSON：{path}")
    if scope not in {SyncScope.ALL, SyncScope.LESSONS}:
        return
    catalog = await lesson_catalog(
        session.page,
        course,
        base_url=settings.ed_base_url,
        region=settings.region,
    )
    if not catalog["lessons"]:
        console.print("这门课程没有可同步的 Lessons，已跳过课程内容。")
        return
    selected: list[int] | None = None
    if group_selection:
        selected = parse_group_selection(
            group_selection, list(range(1, len(catalog["modules"]) + 1))
        )
    with ResourceCache(settings.database) as cache:
        path, counts = await sync_lessons(
            session.context,
            session.page,
            course,
            output_root,
            cache,
            selected_groups=selected,
            base_url=settings.ed_base_url,
            region=settings.region,
            refresh=refresh,
            progress=lambda message: console.print(message, end="\r"),
        )
    console.print(
        f"Lessons：下载 {counts['downloaded']}；未变化 {counts['unchanged']}；"
        f"媒体跳过 {counts['skipped_media']}；仅链接 {counts['link_only']}；"
        f"远端缺失 {counts['missing_remote']}；失败 {counts['failed']}。"
    )
    console.print(f"课程目录：{path}")


@app.command()
def sync(
    course: Annotated[str | None, typer.Option("--course", "-c")] = None,
    all_courses: Annotated[bool, typer.Option("--all")] = False,
    scope: Annotated[SyncScope, typer.Option()] = SyncScope.ALL,
    groups: Annotated[str | None, typer.Option("--groups")] = None,
    full: Annotated[bool, typer.Option("--full")] = False,
    refresh: Annotated[bool, typer.Option("--refresh")] = False,
    output: Annotated[Path | None, typer.Option("--output")] = None,
    headed: Annotated[bool, typer.Option("--headed")] = False,
) -> None:
    """Synchronise one course or all current courses."""
    if all_courses == (course is not None):
        raise typer.BadParameter("Choose exactly one of --all or --course.")
    if all_courses and groups:
        raise typer.BadParameter("--groups cannot be combined with --all.")
    if groups and scope is SyncScope.DISCUSSIONS:
        raise typer.BadParameter("--groups only applies to Lessons.")
    run(
        _with_auto_login(
            lambda: _sync(
                selector=course,
                all_courses=all_courses,
                scope=scope,
                groups=groups,
                full=full,
                refresh=refresh,
                output=output,
                headed=headed,
            )
        )
    )


async def _sync(
    *,
    selector: str | None,
    all_courses: bool,
    scope: SyncScope,
    groups: str | None,
    full: bool,
    refresh: bool,
    output: Path | None,
    headed: bool,
) -> None:
    settings = Settings.default()
    output_root = output.expanduser().resolve() if output else settings.output_root
    async with BrowserSession(settings, headless=not headed) as session:
        courses_to_show = await _load_courses(session, settings)
        if all_courses:
            selected = [c for c in courses_to_show if c.status is CourseStatus.CURRENT]
            if not selected or any(c.status is CourseStatus.UNCLASSIFIED for c in courses_to_show):
                raise EdDownloaderError(
                    "Current and archived courses could not be classified safely; "
                    "select one course."
                )
        else:
            selected = [CourseCatalog.resolve(courses_to_show, selector or "")]
        failures: list[str] = []
        for item in selected:
            try:
                await _sync_course(
                    session,
                    settings,
                    item,
                    scope=scope,
                    group_selection=groups,
                    force_full=full,
                    refresh=refresh,
                    output_root=output_root,
                )
            except LoginRequiredError:
                raise
            except Exception as error:  # noqa: BLE001 - all-current continues to the next course
                if not all_courses:
                    raise
                failures.append(f"{item.code}: {error}")
                console.print(f"[red]{item.code} 同步失败：[/red]{error}")
        if failures:
            raise EdDownloaderError(
                f"{len(failures)} course(s) failed; completed courses were kept."
            )


def _prompt_main(courses_to_show: list[Course]) -> Course | str | None:
    current = [course for course in courses_to_show if course.status is CourseStatus.CURRENT]
    archived = [course for course in courses_to_show if course.status is CourseStatus.ARCHIVED]
    console.print("\n[bold]请选择要同步的内容[/bold]")
    console.print("  [cyan]1[/cyan]  一键同步所有当前课程")
    numbered: dict[int, Course] = {}
    number = 2
    console.print("\n[bold]当前课程[/bold]")
    for course in current:
        numbered[number] = course
        console.print(f"  [cyan]{number}[/cyan]  {course.code} — {course.title}")
        number += 1
    for group in dict.fromkeys(course.archive_group or "Archived" for course in archived):
        console.print(f"\n[bold]归档：{group}[/bold]")
        for course in [item for item in archived if (item.archive_group or "Archived") == group]:
            numbered[number] = course
            console.print(f"  [cyan]{number}[/cyan]  {course.code} — {course.title}")
            number += 1
    console.print("\n  [cyan]0[/cyan]  Exit")
    while True:
        choice = typer.prompt("请输入序号", type=int)
        if choice == 0:
            return None
        if choice == 1:
            return "all"
        if choice in numbered:
            return numbered[choice]
        console.print("[yellow]请输入菜单中显示的序号。[/yellow]")


def _prompt_action(course: Course) -> tuple[SyncScope, str | None] | None:
    console.print(f"\n[bold]{course.code} — {course.title}[/bold]")
    console.print("  [cyan]1[/cyan]  同步整门课程")
    console.print("  [cyan]2[/cyan]  只同步 Discussions")
    console.print("  [cyan]3[/cyan]  同步全部 Lessons")
    console.print("  [cyan]4[/cyan]  选择 Week／Module 同步")
    console.print("  [cyan]0[/cyan]  返回课程列表")
    while True:
        choice = typer.prompt("请输入序号", type=int)
        if choice == 0:
            return None
        if choice == 1:
            return SyncScope.ALL, None
        if choice == 2:
            return SyncScope.DISCUSSIONS, None
        if choice == 3:
            return SyncScope.LESSONS, None
        if choice == 4:
            return SyncScope.LESSONS, "prompt"
        console.print("[yellow]请输入 0 到 4。[/yellow]")


@app.command()
def menu() -> None:
    """Open the Finder-friendly interactive menu."""
    run(_with_auto_login(_menu))


async def _menu() -> None:
    settings = Settings.default()
    async with BrowserSession(settings, headless=True) as session:
        courses_to_show = await _load_courses(session, settings)
        while True:
            choice = _prompt_main(courses_to_show)
            if choice is None:
                console.print("已退出 ED Downloader。")
                return
            if choice == "all":
                if any(course.status is CourseStatus.UNCLASSIFIED for course in courses_to_show):
                    console.print("[yellow]无法可靠区分当前和归档课程，请逐门选择。[/yellow]")
                    continue
                targets = [c for c in courses_to_show if c.status is CourseStatus.CURRENT]
                for course in targets:
                    try:
                        await _sync_course(
                            session,
                            settings,
                            course,
                            scope=SyncScope.ALL,
                            group_selection=None,
                            force_full=False,
                            refresh=False,
                            output_root=settings.output_root,
                        )
                    except LoginRequiredError:
                        raise
                    except Exception as error:  # noqa: BLE001 - menu remains usable
                        console.print(f"[red]{course.code} 同步失败：[/red]{error}")
                continue
            assert isinstance(choice, Course)
            action = _prompt_action(choice)
            if action is None:
                continue
            scope, group_selection = action
            if group_selection == "prompt":
                catalog = await lesson_catalog(
                    session.page, choice, base_url=settings.ed_base_url, region=settings.region
                )
                if not catalog["lessons"]:
                    console.print("[yellow]这门课程没有可同步的 Lessons。[/yellow]")
                    continue
                console.print("\n[bold]可用 Week／Module[/bold]")
                for index, group in enumerate(catalog["modules"], 1):
                    console.print(f"  [cyan]{index}[/cyan]  {group.get('name') or 'Ungrouped'}")
                while True:
                    raw = typer.prompt("输入序号，例如 1,3-5；输入 b 返回", type=str)
                    if raw.strip().casefold() == "b":
                        group_selection = None
                        break
                    try:
                        parse_group_selection(raw, list(range(1, len(catalog["modules"]) + 1)))
                        group_selection = raw
                        break
                    except ValueError as error:
                        console.print(f"[yellow]{error}[/yellow]")
                if group_selection is None:
                    continue
            try:
                await _sync_course(
                    session,
                    settings,
                    choice,
                    scope=scope,
                    group_selection=group_selection,
                    force_full=False,
                    refresh=False,
                    output_root=settings.output_root,
                )
            except LoginRequiredError:
                raise
            except Exception as error:  # noqa: BLE001 - recoverable operation error
                console.print(f"[red]同步失败：[/red]{error}")
                console.print("正在返回课程列表。")
