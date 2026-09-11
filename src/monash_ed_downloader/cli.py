from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from typing import Any

import typer
from rich.console import Console
from rich.table import Table

from monash_ed_downloader.courses import CourseCatalog
from monash_ed_downloader.errors import EdDownloaderError
from monash_ed_downloader.models import Course, CourseStatus
from monash_ed_downloader.session import BrowserSession
from monash_ed_downloader.settings import Settings

app = typer.Typer(name="ed-downloader", no_args_is_help=True)
console = Console()


def run[T](operation: Coroutine[Any, Any, T]) -> T:
    try:
        return asyncio.run(operation)
    except EdDownloaderError as error:
        console.print(f"[red]Error:[/red] {error}")
        raise typer.Exit(code=1) from error


@app.command()
def doctor() -> None:
    """Show local paths and basic installation status."""
    settings = Settings.default()
    console.print("Python project: [green]ready[/green]")
    console.print(f"Default output: {settings.output_root}")
    console.print(f"Private state: {settings.state_root}")
    run(_doctor_session(settings))


async def _doctor_session(settings: Settings) -> None:
    async with BrowserSession(settings, headless=True) as session:
        status = await session.status()
    colour = "green" if status.authenticated else "yellow"
    console.print(f"Ed session: [{colour}]{status.message}[/{colour}]")


@app.command()
def login(timeout: int = typer.Option(600, min=30)) -> None:
    """Open Chrome for user-controlled Ed login."""
    run(_login(timeout))


async def _login(timeout: int) -> None:
    settings = Settings.default()
    console.print("Opening Chrome. Complete login and MFA only in the browser window.")
    async with BrowserSession(settings, headless=False) as session:
        await session.open_dashboard()
        status = await session.wait_for_login(timeout_seconds=timeout)
    console.print(f"[green]{status.message}[/green]")


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


@app.command()
def courses() -> None:
    """List current and archived ED courses."""
    run(_courses())


async def _courses() -> None:
    settings = Settings.default()
    async with BrowserSession(settings, headless=True) as session:
        await session.ensure_authenticated()
        items = await CourseCatalog(
            session.page, base_url=settings.ed_base_url, region=settings.region
        ).list_courses()
    console.print(
        _course_table("Current courses", [c for c in items if c.status is CourseStatus.CURRENT])
    )
    archived_groups = sorted(
        {c.archive_group or "Archived" for c in items if c.status is CourseStatus.ARCHIVED}
    )
    for group in archived_groups:
        console.print(_course_table(group, [c for c in items if c.archive_group == group]))
    unclassified = [c for c in items if c.status is CourseStatus.UNCLASSIFIED]
    if unclassified:
        console.print(_course_table("Unclassified courses", unclassified))
