from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class CachedResource:
    course_id: str
    source_url: str
    local_path: str | None
    etag: str | None
    last_modified: str | None
    content_length: int | None
    sha256: str | None
    status: str


class ResourceCache:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.connection = sqlite3.connect(path)
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS resources (
                course_id TEXT NOT NULL,
                source_url TEXT NOT NULL,
                local_path TEXT,
                etag TEXT,
                last_modified TEXT,
                content_length INTEGER,
                sha256 TEXT,
                status TEXT NOT NULL,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (course_id, source_url)
            )
            """
        )
        self.connection.commit()

    def __enter__(self) -> ResourceCache:
        return self

    def __exit__(self, *_args: object) -> None:
        self.connection.close()

    def get(self, course_id: str, source_url: str) -> CachedResource | None:
        row = self.connection.execute(
            """SELECT course_id, source_url, local_path, etag, last_modified,
                      content_length, sha256, status
               FROM resources WHERE course_id = ? AND source_url = ?""",
            (course_id, source_url),
        ).fetchone()
        return CachedResource(*row) if row else None

    def put(self, resource: CachedResource) -> None:
        self.connection.execute(
            """
            INSERT INTO resources (
                course_id, source_url, local_path, etag, last_modified,
                content_length, sha256, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(course_id, source_url) DO UPDATE SET
                local_path=excluded.local_path,
                etag=excluded.etag,
                last_modified=excluded.last_modified,
                content_length=excluded.content_length,
                sha256=excluded.sha256,
                status=excluded.status,
                updated_at=CURRENT_TIMESTAMP
            """,
            (
                resource.course_id,
                resource.source_url,
                resource.local_path,
                resource.etag,
                resource.last_modified,
                resource.content_length,
                resource.sha256,
                resource.status,
            ),
        )
        self.connection.commit()
