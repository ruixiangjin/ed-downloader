from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, cast
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

SENSITIVE_QUERY_KEYS = {"access_token", "auth", "key", "signature", "sesskey", "token"}


class CourseStatus(StrEnum):
    CURRENT = "current"
    ARCHIVED = "archived"
    UNCLASSIFIED = "unclassified"


class ResourceStatus(StrEnum):
    DOWNLOADED = "downloaded"
    UNCHANGED = "unchanged"
    LINK_ONLY = "link_only"
    SKIPPED_MEDIA = "skipped_media"
    MISSING_REMOTE = "missing_remote"
    FAILED = "failed"


@dataclass(slots=True)
class Course:
    id: str
    title: str
    url: str
    status: CourseStatus
    archive_group: str | None = None

    @property
    def code(self) -> str:
        import re

        match = re.search(r"(?<![A-Z0-9])([A-Z]{2,4}\d{4})(?!\d)", self.title, re.I)
        return match.group(1).upper() if match else f"ED{self.id}"


@dataclass(slots=True)
class Resource:
    source_url: str
    name: str
    status: ResourceStatus = ResourceStatus.LINK_ONLY
    local_path: str | None = None
    mime_type: str | None = None
    size: int | None = None
    etag: str | None = None
    last_modified: str | None = None
    sha256: str | None = None
    reason: str | None = None


@dataclass(slots=True)
class LessonGroup:
    id: str
    name: str
    index: int
    lessons: list[dict[str, Any]] = field(default_factory=list)


@dataclass(slots=True)
class SyncManifest:
    course: Course
    lesson_groups: list[LessonGroup] = field(default_factory=list)
    generated_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    schema_version: int = field(default=1, init=False)

    def to_dict(self) -> dict[str, Any]:
        return cast(dict[str, Any], sanitise_data(asdict(self)))


def sanitise_url(value: str) -> str:
    parsed = urlparse(value)
    query = [
        (key, item)
        for key, item in parse_qsl(parsed.query, keep_blank_values=True)
        if key.casefold() not in SENSITIVE_QUERY_KEYS
        and not key.casefold().startswith("x-amz-")
    ]
    return urlunparse(parsed._replace(query=urlencode(query)))


def sanitise_data(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: sanitise_data(item) for key, item in value.items()}
    if isinstance(value, list):
        return [sanitise_data(item) for item in value]
    if isinstance(value, str) and value.startswith(("http://", "https://")):
        return sanitise_url(value)
    return value
