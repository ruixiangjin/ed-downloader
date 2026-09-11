from typer.testing import CliRunner

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
