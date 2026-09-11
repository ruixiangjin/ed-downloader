from __future__ import annotations

import hashlib
import mimetypes
import os
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlparse

from playwright.async_api import APIRequestContext, APIResponse

from monash_ed_downloader.cache import CachedResource, ResourceCache
from monash_ed_downloader.models import Resource, ResourceStatus, sanitise_url
from monash_ed_downloader.utils import safe_filename

MEDIA_PREFIXES = ("image/", "video/", "audio/", "font/")
MEDIA_EXTENSIONS = {
    ".avif",
    ".gif",
    ".ico",
    ".jpeg",
    ".jpg",
    ".m4a",
    ".m4v",
    ".mkv",
    ".mov",
    ".mp3",
    ".mp4",
    ".ogg",
    ".otf",
    ".png",
    ".svg",
    ".ttf",
    ".wav",
    ".webm",
    ".webp",
    ".woff",
    ".woff2",
}
DOWNLOADABLE_PREFIXES = ("application/", "text/")
HTML_TYPES = {"text/html", "application/xhtml+xml"}


@dataclass(slots=True)
class DownloadCounts:
    downloaded: int = 0
    unchanged: int = 0
    skipped_media: int = 0
    link_only: int = 0
    missing_remote: int = 0
    failed: int = 0


def content_disposition_filename(value: str) -> str:
    encoded = re.search(r"filename\*=UTF-8''([^;]+)", value, re.I)
    if encoded:
        return unquote(encoded.group(1).strip('"'))
    plain = re.search(r'filename="([^"]+)"', value, re.I) or re.search(
        r"filename=([^;]+)", value, re.I
    )
    return plain.group(1).strip() if plain else ""


def is_media(url: str, content_type: str = "") -> bool:
    media_type = content_type.split(";", 1)[0].strip().casefold()
    suffix = Path(urlparse(url).path).suffix.casefold()
    return media_type.startswith(MEDIA_PREFIXES) or suffix in MEDIA_EXTENSIONS


def is_direct_file_candidate(url: str) -> bool:
    suffix = Path(urlparse(url).path).suffix.casefold()
    return bool(suffix and suffix not in MEDIA_EXTENSIONS) or bool(
        re.search(r"/(?:files?|attachments?|download)/", urlparse(url).path, re.I)
    )


class ResourceDownloader:
    def __init__(
        self,
        request: APIRequestContext,
        cache: ResourceCache,
        *,
        course_id: str,
        course_root: Path,
        refresh: bool = False,
    ) -> None:
        self.request = request
        self.cache = cache
        self.course_id = course_id
        self.course_root = course_root
        self.refresh = refresh
        self.counts = DownloadCounts()

    async def _fetch(self, method: str, url: str) -> APIResponse:
        return await self.request.fetch(
            url,
            method=method,
            timeout=45_000,
            max_redirects=5,
            fail_on_status_code=False,
        )

    async def download(self, url: str, target_directory: Path, preferred_name: str) -> Resource:
        safe_url = sanitise_url(url)
        if is_media(url):
            self.counts.skipped_media += 1
            return Resource(
                safe_url, preferred_name, ResourceStatus.SKIPPED_MEDIA, reason="media-link-only"
            )
        cached = self.cache.get(self.course_id, safe_url)
        try:
            head = await self._fetch("HEAD", url)
            headers = head.headers
            status = head.status
        except Exception:  # noqa: BLE001 - GET still provides a safe fallback
            headers, status = {}, 0
        local = Path(cached.local_path) if cached and cached.local_path else None
        if local and not local.is_absolute():
            local = self.course_root / local
        etag = headers.get("etag")
        modified = headers.get("last-modified")
        length_text = headers.get("content-length", "")
        length = int(length_text) if length_text.isdigit() else None
        if (
            not self.refresh
            and cached
            and local
            and local.is_file()
            and (
                (
                    bool(etag or modified)
                    and cached.etag == etag
                    and cached.last_modified == modified
                )
                or (
                    not etag
                    and not modified
                    and length is not None
                    and cached.content_length == length
                )
            )
        ):
            self.counts.unchanged += 1
            return Resource(
                safe_url,
                preferred_name,
                ResourceStatus.UNCHANGED,
                local_path=local.relative_to(self.course_root).as_posix(),
                etag=etag,
                last_modified=modified,
                size=length,
                sha256=cached.sha256,
            )
        if status in {404, 410}:
            self.counts.missing_remote += 1
            return self._remembered(cached, preferred_name, ResourceStatus.MISSING_REMOTE)
        try:
            response = await self._fetch("GET", url)
            headers = response.headers
            content_type = headers.get("content-type", "").split(";", 1)[0].casefold()
            if response.status in {404, 410}:
                self.counts.missing_remote += 1
                return self._remembered(cached, preferred_name, ResourceStatus.MISSING_REMOTE)
            if not response.ok:
                raise RuntimeError(f"HTTP {response.status}")
            if is_media(url, content_type):
                self.counts.skipped_media += 1
                return Resource(
                    safe_url,
                    preferred_name,
                    ResourceStatus.SKIPPED_MEDIA,
                    mime_type=content_type,
                    reason="media-link-only",
                )
            if content_type in HTML_TYPES or not content_type.startswith(DOWNLOADABLE_PREFIXES):
                self.counts.link_only += 1
                return Resource(
                    safe_url,
                    preferred_name,
                    ResourceStatus.LINK_ONLY,
                    mime_type=content_type,
                    reason="not-a-direct-non-media-file",
                )
            body = await response.body()
        except Exception as error:  # noqa: BLE001 - preserve prior complete file
            if cached and local and local.is_file():
                self.counts.unchanged += 1
                return self._remembered(cached, preferred_name, ResourceStatus.UNCHANGED)
            self.counts.failed += 1
            return Resource(safe_url, preferred_name, ResourceStatus.FAILED, reason=str(error))
        remote_name = content_disposition_filename(headers.get("content-disposition", ""))
        remote_name = remote_name or unquote(Path(urlparse(url).path).name)
        suffix = Path(remote_name).suffix or mimetypes.guess_extension(content_type) or ".bin"
        filename = f"{safe_filename(preferred_name or Path(remote_name).stem)}{suffix}"
        target_directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        target = target_directory / filename
        digest = hashlib.sha256(body).hexdigest()
        if target.is_file() and hashlib.sha256(target.read_bytes()).hexdigest() == digest:
            result_status = ResourceStatus.UNCHANGED
            self.counts.unchanged += 1
        else:
            temporary = target.with_name(f".{target.name}.{os.getpid()}.part")
            temporary.write_bytes(body)
            os.chmod(temporary, 0o600)
            temporary.replace(target)
            result_status = ResourceStatus.DOWNLOADED
            self.counts.downloaded += 1
        relative = target.relative_to(self.course_root).as_posix()
        result = Resource(
            safe_url,
            filename,
            result_status,
            local_path=relative,
            mime_type=content_type,
            size=len(body),
            etag=headers.get("etag"),
            last_modified=headers.get("last-modified"),
            sha256=digest,
        )
        self.cache.put(
            CachedResource(
                self.course_id,
                safe_url,
                relative,
                result.etag,
                result.last_modified,
                len(body),
                digest,
                result.status,
            )
        )
        return result

    def _remembered(
        self, cached: CachedResource | None, name: str, status: ResourceStatus
    ) -> Resource:
        return Resource(
            cached.source_url if cached else "",
            name,
            status,
            local_path=cached.local_path if cached else None,
            etag=cached.etag if cached else None,
            last_modified=cached.last_modified if cached else None,
            size=cached.content_length if cached else None,
            sha256=cached.sha256 if cached else None,
        )
