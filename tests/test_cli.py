from io import StringIO

import pytest
import typer
from rich.console import Console
from typer.testing import CliRunner

import monash_ed_downloader.cli as cli_module
from monash_ed_downloader.cli import app


def test_help_lists_main_workflows() -> None:
    result = CliRunner().invoke(app, ["--help"])
    assert result.exit_code == 0
    for command in ("login", "doctor", "courses", "scan", "sync", "menu"):
        assert command in result.stdout


def test_sync_requires_exactly_one_course_selector() -> None:
    result = CliRunner().invoke(app, ["sync"])
    assert result.exit_code != 0
    assert "exactly one" in result.output


def test_menu_reprompts_for_non_numeric_input_in_english(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    answers = iter(["not-a-number", "2"])
    output = StringIO()
    monkeypatch.setattr(typer, "prompt", lambda *_args, **_kwargs: next(answers))
    monkeypatch.setattr(
        cli_module,
        "console",
        Console(file=output, force_terminal=False, color_system=None),
    )

    assert cli_module._prompt_menu_number("Enter a number") == 2
    assert "Enter a numeric menu choice." in output.getvalue()
