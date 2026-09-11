from pathlib import Path

from monash_ed_downloader.forum import build_known_reply_counts, load_store, merge_scrape
from monash_ed_downloader.models import Course, CourseStatus


def thread(content: str = "Question") -> dict[str, object]:
    return {
        "id": "10",
        "courseId": "39026",
        "number": "1",
        "title": "Hello",
        "url": "https://edstem.org/au/courses/39026/discussion/10",
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
        "source": "https://edstem.org/au/courses/39026/discussion",
        "course": {"id": "39026", "title": "FIT2109", "url": "x", "categories": []},
        "threads": [item],
    }


def test_forum_store_preserves_tags_and_updates_changed_content(tmp_path: Path) -> None:
    course = Course("39026", "FIT2109", "https://example.test", CourseStatus.CURRENT)
    store, path = load_store(course, tmp_path)
    first, stats = merge_scrape(store, result(thread()))
    assert stats["new_threads"] == 1
    assert first["threads"][0]["first_seen_tag"] == 1
    second, stats = merge_scrape(first, result(thread("Edited")))
    assert stats["updated_threads"] == 1
    assert second["threads"][0]["first_seen_tag"] == 1
    assert second["threads"][0]["last_changed_tag"] == 2
    assert path.name == "FIT2109 - Discussions.json"


def test_known_reply_count_includes_answers_and_comments() -> None:
    item = thread()
    item["comments"] = [{"id": "c1"}]
    item["answers"] = [{"id": "a1", "comments": [{"id": "c2"}]}]
    store = {"threads": [item]}
    assert build_known_reply_counts(store) == {"10": 3}
