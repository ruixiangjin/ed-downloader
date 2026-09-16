from pathlib import Path
from typing import Any, cast

import pytest

import monash_ed_downloader.forum as forum_module
from monash_ed_downloader.forum import (
    build_known_reply_counts,
    load_store,
    merge_scrape,
    sync_discussions,
)
from monash_ed_downloader.models import Course, CourseStatus
from monash_ed_downloader.progress import ProgressUpdate


def thread(content: str = "Question") -> dict[str, object]:
    return {
        "id": "10",
        "courseId": "10001",
        "number": "1",
        "title": "Hello",
        "url": "https://edstem.org/au/courses/10001/discussion/10",
        "author": "A",
        "role": "",
        "publishedAt": "2026-01-01",
        "category": "General",
        "content": content,
        "images": ["https://images.test/a.png"],
        "comments": [],
        "answers": [],
    }


def result(item: dict[str, object]) -> dict[str, object]:
    return {
        "mode": "full",
        "exportedAt": "2026-01-01T00:00:00Z",
        "source": "https://edstem.org/au/courses/10001/discussion",
        "course": {"id": "10001", "title": "DEMO1001", "url": "x", "categories": []},
        "threads": [item],
    }


def test_forum_store_preserves_tags_and_updates_changed_content(tmp_path: Path) -> None:
    course = Course("10001", "DEMO1001", "https://example.test", CourseStatus.CURRENT)
    store, path = load_store(course, tmp_path)
    first, stats = merge_scrape(store, result(thread()))
    assert stats["new_threads"] == 1
    assert first["threads"][0]["first_seen_tag"] == 1
    second, stats = merge_scrape(first, result(thread("Edited")))
    assert stats["updated_threads"] == 1
    assert second["threads"][0]["first_seen_tag"] == 1
    assert second["threads"][0]["last_changed_tag"] == 2
    assert path.name == "DEMO1001 - Discussions.json"


def test_known_reply_count_includes_answers_and_comments() -> None:
    item = thread()
    item["comments"] = [{"id": "c1"}]
    item["answers"] = [{"id": "a1", "comments": [{"id": "c2"}]}]
    store = {"threads": [item]}
    assert build_known_reply_counts(store) == {"10": 3}


@pytest.mark.asyncio
async def test_discussion_progress_switches_from_discovery_to_known_total(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    course = Course("10001", "DEMO1001", "https://example.test", CourseStatus.CURRENT)

    async def fake_course_info(_page: object, _course: Course) -> dict[str, object]:
        return {"id": course.id, "title": course.title, "url": course.url, "categories": []}

    async def fake_discover(_page: object, _course_id: str, progress: Any) -> list[str]:
        progress(2)
        return ["https://example.test/1", "https://example.test/2"]

    async def fake_parse(_page: object, url: str, _course_id: str) -> dict[str, object]:
        return thread(url.rsplit("/", 1)[-1])

    monkeypatch.setattr(forum_module, "_course_info", fake_course_info)
    monkeypatch.setattr(forum_module, "_discover_full", fake_discover)
    monkeypatch.setattr(forum_module, "_parse_thread", fake_parse)
    updates: list[ProgressUpdate] = []

    await sync_discussions(
        cast(Any, object()),
        course,
        tmp_path,
        delay_ms=0,
        progress=updates.append,
    )

    assert any(
        update.phase == "discussion-discovery" and update.total is None and update.finished
        for update in updates
    )
    assert any(
        update.phase == "discussion-reading"
        and update.completed == 2
        and update.total == 2
        and update.finished
        for update in updates
    )
