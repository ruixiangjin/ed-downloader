# ruff: noqa: E501
from __future__ import annotations

import hashlib
import html
import json
import os
import re
from collections.abc import Callable
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlparse

from markdownify import markdownify
from playwright.async_api import BrowserContext, Page, Response

from monash_ed_downloader.cache import ResourceCache
from monash_ed_downloader.download import ResourceDownloader, is_direct_file_candidate, is_media
from monash_ed_downloader.errors import LoginRequiredError, SyncSafetyError
from monash_ed_downloader.models import Course, ResourceStatus, sanitise_data
from monash_ed_downloader.utils import (
    normalise_text,
    safe_filename,
    write_json_atomic,
    write_text_atomic,
)


def xml_to_markdown(value: object) -> str:
    text = str(value or "")
    text = re.sub(
        r'<link\b[^>]*href="([^"]+)"[^>]*>([\s\S]*?)</link>', r"[\2](\1)", text, flags=re.I
    )
    text = re.sub(
        r'<heading\b[^>]*level="?(\d+)"?[^>]*>([\s\S]*?)</heading>',
        lambda m: f"\n{'#' * min(6, int(m.group(1)))} {m.group(2)}\n",
        text,
        flags=re.I,
    )
    text = re.sub(r"<list-item\b[^>]*>([\s\S]*?)</list-item>", r"\n- \1", text, flags=re.I)
    text = re.sub(r"<table-row\b[^>]*>([\s\S]*?)</table-row>", r"\n\1", text, flags=re.I)
    text = re.sub(r"<table-cell\b[^>]*>([\s\S]*?)</table-cell>", r"\1 | ", text, flags=re.I)
    text = re.sub(r"<code\b[^>]*>([\s\S]*?)</code>", r"`\1`", text, flags=re.I)
    text = re.sub(r"<break\b[^>]*/?>", "\n", text, flags=re.I)
    text = re.sub(r"</(?:paragraph|document|list|table)>", "\n", text, flags=re.I)
    text = re.sub(r"<(?:paragraph|document|list|table)\b[^>]*>", "", text, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    return re.sub(r"\n{2,}(?=- )", "\n", normalise_text(html.unescape(text)))


def extract_urls(value: object) -> list[str]:
    urls = re.findall(r'https?://[^<\s"]+', str(value or ""), re.I)
    return list(dict.fromkeys(html.unescape(url).rstrip("),.;") for url in urls))


async def _capture_json(page: Page, api_match: str, navigation_url: str) -> dict[str, Any]:
    async with page.expect_response(
        lambda response: response.url == api_match, timeout=25_000
    ) as info:
        await page.goto(navigation_url, wait_until="domcontentloaded")
    response: Response = await info.value
    if not response.ok:
        raise SyncSafetyError(f"Ed returned HTTP {response.status} for course content.")
    return cast(dict[str, Any], await response.json())


async def lesson_catalog(
    page: Page, course: Course, *, base_url: str, region: str
) -> dict[str, Any]:
    lessons_url = f"{base_url}/{region}/courses/{course.id}/lessons"
    body = await _capture_json(page, f"{base_url}/api/courses/{course.id}/lessons", lessons_url)
    if not await page.locator('[data-testid="appbar-user"]').is_visible():
        raise LoginRequiredError("Ed login is required.")
    return {
        "lessons": body.get("lessons", []),
        "modules": body.get("modules", []),
        "source_url": lessons_url,
    }


async def lesson_detail(
    page: Page, course: Course, lesson_id: object, *, base_url: str, region: str
) -> dict[str, Any]:
    api = f"{base_url}/api/lessons/{lesson_id}?view=0"
    url = f"{base_url}/{region}/courses/{course.id}/lessons/{lesson_id}"
    return cast(dict[str, Any], (await _capture_json(page, api, url)).get("lesson", {}))


async def quiz_questions(
    page: Page, course: Course, lesson_id: object, slide_id: object, *, base_url: str, region: str
) -> list[dict[str, Any]]:
    fragment = f"/api/lessons/slides/{slide_id}/questions?pool="
    async with page.expect_response(
        lambda response: fragment in response.url, timeout=20_000
    ) as info:
        await page.goto(
            f"{base_url}/{region}/courses/{course.id}/lessons/{lesson_id}/slides/{slide_id}",
            wait_until="domcontentloaded",
        )
    response = await info.value
    if not response.ok:
        raise SyncSafetyError(f"Quiz questions returned HTTP {response.status}.")
    return cast(list[dict[str, Any]], (await response.json()).get("questions", []))


async def extract_webpage(page: Page, url: str) -> dict[str, Any]:
    response = await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
    if response is None or not response.ok:
        raise SyncSafetyError(f"Course webpage could not be read: {url}")
    content_type = response.headers.get("content-type", "").casefold()
    if "text/html" not in content_type:
        raise SyncSafetyError(f"Course webpage is not HTML: {url}")
    final_host = urlparse(page.url).hostname or ""
    if "login" in page.url.casefold() or "okta" in final_host.casefold():
        raise SyncSafetyError(f"Course webpage redirected to a login page: {url}")
    await page.wait_for_timeout(250)
    data = cast(
        dict[str, Any],
        await page.evaluate(
            """() => {const root=document.querySelector('main,article,[role=\"main\"]')||document.body;const absolute=v=>{try{return new URL(v,document.baseURI).href}catch{return ''}};return{title:document.title,html:root.innerHTML,links:[...new Set([...root.querySelectorAll('a[href]')].map(a=>absolute(a.getAttribute('href'))).filter(Boolean))],media:[...new Set([...root.querySelectorAll('img[src],video[src],video source[src],audio[src],audio source[src],iframe[src]')].map(e=>absolute(e.getAttribute('src'))).filter(Boolean))]}}"""
        ),
    )
    markdown = markdownify(str(data.get("html", "")), heading_style="ATX")
    return {
        "source_url": url,
        "title": data.get("title", ""),
        "markdown": normalise_text(markdown),
        "links": data.get("links", []),
        "media": data.get("media", []),
    }


def _question(question: dict[str, Any]) -> dict[str, Any]:
    data = question.get("data") or {}
    return {
        "id": question.get("id"),
        "index": question.get("index"),
        "type": data.get("type", ""),
        "points": question.get("auto_points"),
        "multiple_selection": bool(data.get("multiple_selection")),
        "text": xml_to_markdown(data.get("content")),
        "answers": [xml_to_markdown(answer) for answer in data.get("answers", [])],
    }


def _lesson_markdown(
    course: Course, lesson: dict[str, Any], *, lesson_file: Path, course_root: Path
) -> str:
    lines = [
        f"# {lesson.get('title') or 'Untitled Lesson'}",
        "",
        f"Source: {lesson.get('source_url')}",
        "",
    ]
    for slide in lesson.get("slides", []):
        lines.extend(
            [
                f"## {slide.get('title') or 'Untitled'}",
                "",
                f"Type: `{slide.get('type') or 'unknown'}`",
                "",
            ]
        )
        if slide.get("text"):
            lines.extend([str(slide["text"]), ""])
        page = slide.get("page") or {}
        if page.get("markdown"):
            lines.extend([str(page["markdown"]), ""])
        if slide.get("questions"):
            for number, question in enumerate(slide["questions"], 1):
                lines.extend([f"### Question {number}", "", str(question.get("text", "")), ""])
                for index, answer in enumerate(question.get("answers", []), 1):
                    lines.append(f"- {index}. {answer}")
                lines.append("")
        for resource in [
            slide.get("file"),
            *(slide.get("resources") or []),
            *(page.get("files") or []),
        ]:
            if not resource:
                continue
            label = resource.get("name") or "Resource"
            target = resource.get("source_url")
            if resource.get("local_path"):
                target = os.path.relpath(
                    course_root / resource["local_path"], lesson_file.parent
                ).replace(os.sep, "/")
            lines.append(f"- [{label}]({target}) — {resource.get('status')}")
        for media in [*(slide.get("media") or []), *(page.get("media") or [])]:
            lines.append(f"- [Media link]({media}) — not downloaded")
        if slide.get("unsupported"):
            lines.append(f"- [Open this item]({slide.get('source_url')}) — unsupported type")
        lines.append("")
    return "\n".join(lines).replace("\n\n\n", "\n\n").rstrip() + "\n"


def _index_markdown(course: Course, groups: list[dict[str, Any]], checked_at: str) -> str:
    lines = [
        f"# {course.title} - Lessons",
        "",
        f"Source: {course.url.rsplit('/discussion', 1)[0]}/lessons",
        "",
        f"Last checked: {checked_at}",
        "",
    ]
    for group in groups:
        lines.extend([f"## {group.get('name') or 'Ungrouped'}", ""])
        for lesson in group.get("lessons", []):
            path = lesson.get("markdown_path")
            lines.append(
                f"- [{lesson.get('title') or 'Untitled'}]({path})"
                if path
                else f"- {lesson.get('title') or 'Untitled'}"
            )
        lines.append("")
    return "\n".join(lines).replace("\n\n\n", "\n\n").rstrip() + "\n"


async def sync_lessons(
    context: BrowserContext,
    page: Page,
    course: Course,
    output_root: Path,
    cache: ResourceCache,
    *,
    selected_groups: list[int] | None = None,
    base_url: str = "https://edstem.org",
    region: str = "au",
    refresh: bool = False,
    progress: Callable[[str], None] = lambda _message: None,
) -> tuple[Path, dict[str, int]]:
    catalog = await lesson_catalog(page, course, base_url=base_url, region=region)
    modules = list(catalog["modules"])
    summaries = list(catalog["lessons"])
    known_module_ids = {str(module.get("id")) for module in modules}
    if any(str(summary.get("module_id")) not in known_module_ids for summary in summaries):
        modules.append({"id": "ungrouped", "name": "Ungrouped"})
        for summary in summaries:
            if str(summary.get("module_id")) not in known_module_ids:
                summary["module_id"] = "ungrouped"
    course_root = output_root / safe_filename(course.title)
    lessons_root = course_root / "Lessons"
    manifest_path = lessons_root / f"{safe_filename(course.title)} - Last Sync.json"
    previous: dict[str, Any] = {}
    if manifest_path.exists():
        previous = json.loads(manifest_path.read_text(encoding="utf-8"))
    previous_groups = {str(item.get("id")): item for item in previous.get("groups", [])}
    previous_slides = {
        str(slide.get("id")): slide
        for group in previous.get("groups", [])
        for lesson in group.get("lessons", [])
        for slide in lesson.get("slides", [])
    }
    requested = set(selected_groups or range(1, len(modules) + 1))
    if requested.difference(range(1, len(modules) + 1)):
        raise ValueError("Selected Lesson group is unavailable.")
    by_module: dict[str, list[dict[str, Any]]] = {}
    order = {str(module.get("id")): index for index, module in enumerate(modules)}
    summaries.sort(
        key=lambda item: (order.get(str(item.get("module_id")), 999), item.get("index", 999))
    )
    for summary in summaries:
        by_module.setdefault(str(summary.get("module_id")), []).append(summary)
    content_page = await context.new_page()
    downloader = ResourceDownloader(
        context.request,
        cache,
        course_id=course.id,
        course_root=course_root,
        refresh=refresh,
    )
    groups: list[dict[str, Any]] = []
    try:
        for group_index, module in enumerate(modules, 1):
            module_id = str(module.get("id"))
            if group_index not in requested:
                groups.append(
                    previous_groups.get(
                        module_id,
                        {
                            "id": module_id,
                            "name": module.get("name", ""),
                            "index": group_index,
                            "lessons": [],
                        },
                    )
                )
                continue
            group_directory = (
                lessons_root / f"{group_index:02d}-{safe_filename(module.get('name'))}"
            )
            lessons: list[dict[str, Any]] = []
            for lesson_index, summary in enumerate(by_module.get(module_id, []), 1):
                progress(f"Reading {module.get('name')}: {summary.get('title')}")
                detail = await lesson_detail(
                    page, course, summary.get("id"), base_url=base_url, region=region
                )
                lesson_directory = (
                    group_directory / f"{lesson_index:02d}-{safe_filename(detail.get('title'))}"
                )
                slides: list[dict[str, Any]] = []
                for slide_index, raw in enumerate(
                    sorted(detail.get("slides", []), key=lambda item: item.get("index", 999)), 1
                ):
                    slide = {
                        "id": raw.get("id"),
                        "index": raw.get("index"),
                        "title": raw.get("title", ""),
                        "type": raw.get("type", ""),
                        "source_url": f"{base_url}/{region}/courses/{course.id}/lessons/{detail.get('id')}/slides/{raw.get('id')}",
                    }
                    preferred = f"{slide_index:02d}-{slide['title'] or 'resource'}"
                    if raw.get("content"):
                        slide["text"] = xml_to_markdown(raw["content"])
                        slide["media"] = [
                            url for url in extract_urls(raw["content"]) if is_media(url)
                        ]
                        resources: list[dict[str, Any]] = []
                        for url in extract_urls(raw["content"]):
                            if is_direct_file_candidate(url) and not is_media(url):
                                resources.append(
                                    asdict(
                                        await downloader.download(
                                            url, lesson_directory / "Files", preferred
                                        )
                                    )
                                )
                        slide["resources"] = resources
                    if raw.get("file_url"):
                        resource = await downloader.download(
                            str(raw["file_url"]), lesson_directory / "Files", preferred
                        )
                        slide["file"] = asdict(resource)
                        if resource.status is ResourceStatus.FAILED:
                            raise SyncSafetyError(
                                f"Required Lesson file failed: {detail.get('title')} / {slide['title']}"
                            )
                    if raw.get("type") == "webpage" and raw.get("url"):
                        try:
                            page_data = await extract_webpage(content_page, str(raw["url"]))
                            page_files: list[dict[str, Any]] = []
                            for url in page_data["links"]:
                                if is_direct_file_candidate(url) and not is_media(url):
                                    page_files.append(
                                        asdict(
                                            await downloader.download(
                                                url, lesson_directory / "Files", preferred
                                            )
                                        )
                                    )
                            page_data["files"] = page_files
                            slide["page"] = page_data
                        except SyncSafetyError:
                            old_page = previous_slides.get(str(raw.get("id")), {}).get("page")
                            if old_page and old_page.get("markdown"):
                                slide["page"] = {**old_page, "stale": True}
                            else:
                                raise
                    if raw.get("type") == "quiz":
                        try:
                            questions = await quiz_questions(
                                page,
                                course,
                                detail.get("id"),
                                raw.get("id"),
                                base_url=base_url,
                                region=region,
                            )
                            saved_questions = [_question(question) for question in questions]
                        except SyncSafetyError:
                            saved_questions = previous_slides.get(str(raw.get("id")), {}).get(
                                "questions"
                            )
                            if saved_questions is None:
                                raise
                        slide["passage"] = xml_to_markdown(raw.get("passage"))
                        slide["questions"] = saved_questions
                    if raw.get("type") not in {"document", "code", "pdf", "webpage", "quiz"}:
                        slide["unsupported"] = True
                    slides.append(cast(dict[str, Any], sanitise_data(slide)))
                lesson = {
                    "id": detail.get("id"),
                    "module_id": module_id,
                    "index": detail.get("index"),
                    "title": detail.get("title", ""),
                    "kind": detail.get("kind", ""),
                    "type": detail.get("type", ""),
                    "source_url": f"{base_url}/{region}/courses/{course.id}/lessons/{detail.get('id')}",
                    "slides": slides,
                }
                lesson_file = lesson_directory / f"{safe_filename(detail.get('title'))}.md"
                write_text_atomic(
                    lesson_file,
                    _lesson_markdown(
                        course, lesson, lesson_file=lesson_file, course_root=course_root
                    ),
                )
                lesson["markdown_path"] = os.path.relpath(lesson_file, lessons_root).replace(
                    os.sep, "/"
                )
                lesson["content_hash"] = hashlib.sha256(
                    json.dumps(slides, sort_keys=True).encode()
                ).hexdigest()
                lessons.append(lesson)
            groups.append(
                {
                    "id": module_id,
                    "name": module.get("name", ""),
                    "index": group_index,
                    "lessons": lessons,
                }
            )
    finally:
        await content_page.close()
    existing_ids = {str(module.get("id")) for module in modules}
    for group_id, old_group in previous_groups.items():
        if group_id not in existing_ids:
            groups.append({**old_group, "status": "missing_remote"})
    checked_at = datetime.now(UTC).isoformat()
    manifest = {
        "schema_version": 1,
        "course": {
            "id": course.id,
            "code": course.code,
            "title": course.title,
            "source_url": catalog["source_url"],
        },
        "last_checked_at": checked_at,
        "selected_groups": sorted(requested),
        "groups": groups,
        "last_run": asdict(downloader.counts),
    }
    write_json_atomic(manifest_path, sanitise_data(manifest))
    index_path = lessons_root / f"{safe_filename(course.title)} - Lessons.md"
    write_text_atomic(index_path, _index_markdown(course, groups, checked_at))
    return index_path, asdict(downloader.counts)
