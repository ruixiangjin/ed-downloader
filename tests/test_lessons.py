from pathlib import Path
from typing import Any, cast

import pytest

from monash_ed_downloader.download import (
    ResourceDownloader,
    content_disposition_filename,
    is_direct_file_candidate,
    is_media,
)
from monash_ed_downloader.lessons import (
    extract_media_urls,
    selected_lesson_count,
    sortable_index,
    xml_to_markdown,
)
from monash_ed_downloader.models import ResourceStatus
from monash_ed_downloader.progress import ProgressUpdate
from monash_ed_downloader.selection import parse_group_selection


def test_ed_xml_becomes_readable_markdown() -> None:
    value = '<document><heading level="2">Setup</heading><paragraph>Read <link href="https://example.test">this</link>.</paragraph><list><list-item><paragraph>First</paragraph></list-item></list></document>'
    assert xml_to_markdown(value) == "## Setup\nRead [this](https://example.test).\n- First"


def test_extensionless_ed_media_is_recognised_from_xml_tag() -> None:
    value = (
        '<document><image src="https://static.edusercontent.com/files/opaque-image">'
        '<link href="https://static.edusercontent.com/files/opaque-document">file</link>'
        "</document>"
    )
    assert extract_media_urls(value) == ["https://static.edusercontent.com/files/opaque-image"]


def test_media_is_link_only_by_mime_or_extension() -> None:
    assert is_media("https://static.test/no-extension", "image/png")
    assert is_media("https://static.test/video.mp4")
    assert not is_media("https://static.test/notes.pdf", "application/pdf")


@pytest.mark.parametrize(
    "url",
    [
        "https://static.test/notes.pdf",
        "https://static.test/slides.PPTX?download=1",
        "https://static.test/source.java",
        "https://static.test/notebook.ipynb",
        "https://static.test/project.zip",
        "https://static.edusercontent.com/files/opaque-id",
        "https://learning.monash.edu/mod/resource/view.php?id=1",
    ],
)
def test_direct_file_candidate_accepts_course_file_whitelist(url: str) -> None:
    assert is_direct_file_candidate(url)


@pytest.mark.parametrize(
    "url",
    [
        "https://www.gnu.org/software/bash/manual/bash.html",
        "https://example.test/article.htm",
        "https://example.test/page.php?id=1",
        "https://example.test/view.aspx?id=1",
        "https://example.test/image.png",
        "https://example.test/no-file-here",
        "https://notedusercontent.com/files/opaque-id",
    ],
)
def test_direct_file_candidate_rejects_webpages_and_media(url: str) -> None:
    assert not is_direct_file_candidate(url)


class FakeResponse:
    def __init__(self, content_type: str) -> None:
        self.headers = {"content-type": content_type}
        self.status = 200
        self.ok = True


class FakeRequest:
    def __init__(self, content_type: str) -> None:
        self.content_type = content_type
        self.methods: list[str] = []

    async def fetch(self, _url: str, *, method: str, **_kwargs: object) -> FakeResponse:
        self.methods.append(method)
        return FakeResponse(self.content_type)


class EmptyCache:
    def get(self, _course_id: str, _source_url: str) -> None:
        return None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("content_type", "expected_status"),
    [
        ("image/png", ResourceStatus.SKIPPED_MEDIA),
        ("text/html", ResourceStatus.LINK_ONLY),
    ],
)
async def test_head_response_avoids_unnecessary_get(
    tmp_path: Path, content_type: str, expected_status: ResourceStatus
) -> None:
    request = FakeRequest(content_type)
    updates: list[ProgressUpdate] = []
    downloader = ResourceDownloader(
        cast(Any, request),
        cast(Any, EmptyCache()),
        course_id="10001",
        course_root=tmp_path,
        progress=updates.append,
    )

    result = await downloader.download(
        "https://static.edusercontent.com/files/opaque-id",
        tmp_path / "Files",
        "resource",
    )

    assert result.status is expected_status
    assert request.methods == ["HEAD"]
    assert updates == [ProgressUpdate("resources", "Checking resource: resource", 1)]


def test_content_disposition_prefers_utf8_filename() -> None:
    assert (
        content_disposition_filename("inline; filename=old.pdf; filename*=UTF-8''week%201.pdf")
        == "week 1.pdf"
    )


def test_group_selection_supports_ranges_and_chinese_punctuation() -> None:
    assert parse_group_selection("1，3～5", [1, 2, 3, 4, 5]) == [1, 3, 4, 5]


def test_group_selection_supports_common_separators_and_dashes() -> None:
    assert parse_group_selection("1、3–5；7", list(range(1, 8))) == [1, 3, 4, 5, 7]


@pytest.mark.parametrize("value", ["hello", "1,,2", "3-1"])
def test_group_selection_rejects_invalid_input(value: str) -> None:
    with pytest.raises(ValueError):
        parse_group_selection(value, [1, 2, 3])


def test_group_selection_rejects_numbers_outside_available_range() -> None:
    with pytest.raises(ValueError, match="outside the available range"):
        parse_group_selection("1,4", [1, 2, 3])


def test_missing_lesson_positions_sort_after_numbered_positions() -> None:
    values = [None, 2, "1", "not-a-number"]
    assert sorted(values, key=sortable_index) == ["1", 2, None, "not-a-number"]


def test_lesson_progress_total_only_counts_selected_groups() -> None:
    modules = [{"id": "a"}, {"id": "b"}, {"id": "c"}]
    lessons: dict[str, list[dict[str, object]]] = {
        "a": [{}, {}],
        "b": [{}],
        "c": [{}, {}, {}],
    }

    assert selected_lesson_count(modules, lessons, {1, 3}) == 5
