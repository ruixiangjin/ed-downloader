from io import StringIO

from rich.console import Console

from monash_ed_downloader.progress import ProgressUpdate, TerminalProgress, scoped_progress


def test_non_interactive_progress_uses_plain_lines_without_ansi() -> None:
    output = StringIO()
    console = Console(file=output, force_terminal=False, color_system=None)

    with TerminalProgress(console) as progress:
        progress.update(ProgressUpdate("threads", "Reading discussions", 0, 2))
        progress.update(ProgressUpdate("threads", "Reading discussions", 2, 2, True))

    rendered = output.getvalue()
    assert "Reading discussions [0/2]" in rendered
    assert "Reading discussions [2/2] - done" in rendered
    assert "\x1b" not in rendered


def test_scoped_progress_keeps_course_phases_separate() -> None:
    updates: list[ProgressUpdate] = []
    report = scoped_progress(updates.append, "course-10001")

    report(ProgressUpdate("lessons", "Processing lessons", 1, 3))

    assert updates == [ProgressUpdate("course-10001:lessons", "Processing lessons", 1, 3)]
