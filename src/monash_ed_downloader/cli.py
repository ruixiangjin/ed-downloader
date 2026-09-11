from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from typing import Any

import typer
from rich.console import Console

from monash_ed_downloader.errors import EdDownloaderError
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
