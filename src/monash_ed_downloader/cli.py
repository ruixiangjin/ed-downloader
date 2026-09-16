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
from monash_ed_downloader.progress import (
    ProgressCallback,
    ProgressUpdate,
    TerminalProgress,
    ignore_progress,
    scoped_progress,
)
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
        console.print(f"[red]Error:[/red] {error}")
        raise typer.Exit(code=1) from error


async def _login(timeout: int) -> None:
    settings = Settings.default()
    console.print("Opening Chrome. Complete Ed login and university MFA only in the browser.")
    await interactive_login(settings, timeout_seconds=timeout, notify=console.print)


async def _with_auto_login[T](operation: Callable[[], Awaitable[T]]) -> T:
    settings = Settings.default()
    if not has_confirmed_login(settings):
        console.print("No confirmed Ed session was found. Opening the login flow.")
        await _login(600)
    try:
        return await operation()
    except LoginRequiredError:
        clear_login_confirmation(settings)
        console.print("The Ed session is no longer valid. Opening the login flow.")
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


async def _load_courses(
    session: BrowserSession,
    settings: Settings,
    progress: ProgressCallback = ignore_progress,
) -> list[Course]:
    progress(ProgressUpdate("loading-courses", "Loading courses"))
    await session.ensure_authenticated()
    courses_to_show = await CourseCatalog(
        session.page, base_url=settings.ed_base_url, region=settings.region
    ).list_courses()
    progress(
        ProgressUpdate(
            "loading-courses",
            "Loading courses",
            completed=len(courses_to_show),
            finished=True,
        )
    )
    return courses_to_show


@app.command()
def courses() -> None:
    """List current and archived ED courses."""
    run(_with_auto_login(_courses))


async def _courses() -> None:
    settings = Settings.default()
    async with BrowserSession(settings, headless=True) as session:
        with TerminalProgress(console) as display:
            items = await _load_courses(session, settings, display.update)
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
        with TerminalProgress(console) as display:
            courses_to_show = await _load_courses(session, settings, display.update)
            course = CourseCatalog.resolve(courses_to_show, selector)
            display.update(ProgressUpdate("lesson-catalog", "Loading lesson groups"))
            catalog = await lesson_catalog(
                session.page,
                course,
                base_url=settings.ed_base_url,
                region=settings.region,
            )
            display.update(
                ProgressUpdate(
                    "lesson-catalog",
                    "Loading lesson groups",
                    completed=len(catalog["modules"]),
                    finished=True,
                )
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
    progress: ProgressCallback = ignore_progress,
) -> None:
    console.print(f"\n[bold]{course.code} — {course.title}[/bold]")
    if scope in {SyncScope.ALL, SyncScope.DISCUSSIONS}:
        path, stats = await sync_discussions(
            session.page,
            course,
            output_root,
            force_full=force_full,
            progress=progress,
        )
        console.print(
            f"Discussions: {stats['new_threads']} new; {stats['updated_threads']} updated; "
            f"{stats['unchanged_threads']} unchanged."
        )
        console.print(f"Discussion JSON: {path}")
    if scope not in {SyncScope.ALL, SyncScope.LESSONS}:
        return
    progress(ProgressUpdate("lesson-catalog", "Loading lesson groups"))
    catalog = await lesson_catalog(
        session.page,
        course,
        base_url=settings.ed_base_url,
        region=settings.region,
    )
    progress(
        ProgressUpdate(
            "lesson-catalog",
            "Loading lesson groups",
            completed=len(catalog["modules"]),
            finished=True,
        )
    )
    if not catalog["lessons"]:
        console.print("This course has no downloadable Lessons. Lesson content was skipped.")
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
            progress=progress,
        )
    console.print(
        f"Lessons: {counts['downloaded']} downloaded; {counts['unchanged']} unchanged; "
        f"{counts['skipped_media']} media skipped; {counts['link_only']} links only; "
        f"{counts['missing_remote']} missing remotely; {counts['failed']} failed."
    )
    console.print(f"Course output: {path}")


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
        failures: list[str] = []
        with TerminalProgress(console) as display:
            courses_to_show = await _load_courses(session, settings, display.update)
            if all_courses:
                selected = [c for c in courses_to_show if c.status is CourseStatus.CURRENT]
                if not selected or any(
                    c.status is CourseStatus.UNCLASSIFIED for c in courses_to_show
                ):
                    raise EdDownloaderError(
                        "Current and archived courses could not be classified safely; "
                        "select one course."
                    )
            else:
                selected = [CourseCatalog.resolve(courses_to_show, selector or "")]
            display.update(
                ProgressUpdate(
                    "courses",
                    "Synchronising courses",
                    completed=0,
                    total=len(selected),
                )
            )
            completed_courses = 0
            for course_index, item in enumerate(selected, 1):
                display.update(
                    ProgressUpdate(
                        "courses",
                        f"Synchronising course {course_index} of {len(selected)}: {item.code}",
                        completed=completed_courses,
                        total=len(selected),
                    )
                )
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
                        progress=scoped_progress(display.update, item.id),
                    )
                except LoginRequiredError:
                    raise
                except Exception as error:  # noqa: BLE001 - all-current continues to next course
                    if not all_courses:
                        raise
                    failures.append(f"{item.code}: {error}")
                    console.print(f"[red]{item.code} sync failed:[/red] {error}")
                completed_courses += 1
                display.update(
                    ProgressUpdate(
                        "courses",
                        f"Processed course {course_index} of {len(selected)}: {item.code}",
                        completed=completed_courses,
                        total=len(selected),
                    )
                )
            display.update(
                ProgressUpdate(
                    "courses",
                    "Synchronising courses",
                    completed=completed_courses,
                    total=len(selected),
                    finished=True,
                )
            )
        if failures:
            raise EdDownloaderError(
                f"{len(failures)} course(s) failed; completed course data was kept."
            )


def _prompt_menu_number(message: str) -> int:
    while True:
        raw = typer.prompt(message, type=str).strip()
        try:
            return int(raw)
        except ValueError:
            console.print("[yellow]Enter a numeric menu choice.[/yellow]")


def _prompt_main(courses_to_show: list[Course]) -> Course | str | None:
    current = [course for course in courses_to_show if course.status is CourseStatus.CURRENT]
    archived = [course for course in courses_to_show if course.status is CourseStatus.ARCHIVED]
    console.print("\n[bold]What would you like to synchronise?[/bold]")
    console.print("  [cyan]1[/cyan]  Synchronise all current courses")
    numbered: dict[int, Course] = {}
    number = 2
    console.print("\n[bold]Current courses[/bold]")
    for course in current:
        numbered[number] = course
        console.print(f"  [cyan]{number}[/cyan]  {course.code} — {course.title}")
        number += 1
    for group in dict.fromkeys(course.archive_group or "Archived" for course in archived):
        console.print(f"\n[bold]Archived: {group}[/bold]")
        for course in [item for item in archived if (item.archive_group or "Archived") == group]:
            numbered[number] = course
            console.print(f"  [cyan]{number}[/cyan]  {course.code} — {course.title}")
            number += 1
    console.print("\n  [cyan]0[/cyan]  Exit")
    while True:
        choice = _prompt_menu_number("Enter a number")
        if choice == 0:
            return None
        if choice == 1:
            return "all"
        if choice in numbered:
            return numbered[choice]
        console.print("[yellow]Choose one of the numbers shown above.[/yellow]")


def _prompt_action(course: Course) -> tuple[SyncScope, str | None] | None:
    console.print(f"\n[bold]{course.code} — {course.title}[/bold]")
    console.print("  [cyan]1[/cyan]  Synchronise the entire course")
    console.print("  [cyan]2[/cyan]  Synchronise Discussions only")
    console.print("  [cyan]3[/cyan]  Synchronise all Lessons")
    console.print("  [cyan]4[/cyan]  Select Week/Module groups")
    console.print("  [cyan]0[/cyan]  Back to course selection")
    while True:
        choice = _prompt_menu_number("Enter a number")
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
        console.print("[yellow]Choose 0, 1, 2, 3, or 4.[/yellow]")


@app.command()
def menu() -> None:
    """Open the Finder-friendly interactive menu."""
    run(_with_auto_login(_menu))


async def _menu() -> None:
    settings = Settings.default()
    async with BrowserSession(settings, headless=True) as session:
        with TerminalProgress(console) as display:
            courses_to_show = await _load_courses(session, settings, display.update)
        while True:
            choice = _prompt_main(courses_to_show)
            if choice is None:
                console.print("ED Downloader has exited.")
                return
            if choice == "all":
                if any(course.status is CourseStatus.UNCLASSIFIED for course in courses_to_show):
                    console.print(
                        "[yellow]Current and archived courses could not be classified safely. "
                        "Select courses individually.[/yellow]"
                    )
                    continue
                targets = [c for c in courses_to_show if c.status is CourseStatus.CURRENT]
                with TerminalProgress(console) as display:
                    display.update(
                        ProgressUpdate(
                            "courses",
                            "Synchronising courses",
                            completed=0,
                            total=len(targets),
                        )
                    )
                    completed_courses = 0
                    for course_index, course in enumerate(targets, 1):
                        display.update(
                            ProgressUpdate(
                                "courses",
                                f"Synchronising course {course_index} of "
                                f"{len(targets)}: {course.code}",
                                completed=completed_courses,
                                total=len(targets),
                            )
                        )
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
                                progress=scoped_progress(display.update, course.id),
                            )
                        except LoginRequiredError:
                            raise
                        except Exception as error:  # noqa: BLE001 - menu remains usable
                            console.print(f"[red]{course.code} sync failed:[/red] {error}")
                        completed_courses += 1
                        display.update(
                            ProgressUpdate(
                                "courses",
                                f"Processed course {course_index} of {len(targets)}: {course.code}",
                                completed=completed_courses,
                                total=len(targets),
                            )
                        )
                    display.update(
                        ProgressUpdate(
                            "courses",
                            "Synchronising courses",
                            completed=completed_courses,
                            total=len(targets),
                            finished=True,
                        )
                    )
                continue
            assert isinstance(choice, Course)
            action = _prompt_action(choice)
            if action is None:
                continue
            scope, group_selection = action
            if group_selection == "prompt":
                with TerminalProgress(console) as display:
                    display.update(ProgressUpdate("lesson-catalog", "Loading lesson groups"))
                    catalog = await lesson_catalog(
                        session.page,
                        choice,
                        base_url=settings.ed_base_url,
                        region=settings.region,
                    )
                    display.update(
                        ProgressUpdate(
                            "lesson-catalog",
                            "Loading lesson groups",
                            completed=len(catalog["modules"]),
                            finished=True,
                        )
                    )
                if not catalog["lessons"]:
                    console.print("[yellow]This course has no downloadable Lessons.[/yellow]")
                    continue
                console.print("\n[bold]Available Week/Module groups[/bold]")
                for index, group in enumerate(catalog["modules"], 1):
                    console.print(f"  [cyan]{index}[/cyan]  {group.get('name') or 'Ungrouped'}")
                while True:
                    raw = typer.prompt(
                        "Enter a selection such as 1,3-5, or enter b to go back",
                        type=str,
                    )
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
                with TerminalProgress(console) as display:
                    display.update(
                        ProgressUpdate(
                            "courses",
                            f"Synchronising course: {choice.code}",
                            completed=0,
                            total=1,
                        )
                    )
                    await _sync_course(
                        session,
                        settings,
                        choice,
                        scope=scope,
                        group_selection=group_selection,
                        force_full=False,
                        refresh=False,
                        output_root=settings.output_root,
                        progress=scoped_progress(display.update, choice.id),
                    )
                    display.update(
                        ProgressUpdate(
                            "courses",
                            f"Synchronised course: {choice.code}",
                            completed=1,
                            total=1,
                            finished=True,
                        )
                    )
            except LoginRequiredError:
                raise
            except Exception as error:  # noqa: BLE001 - recoverable operation error
                console.print(f"[red]Sync failed:[/red] {error}")
                console.print("Returning to course selection.")
