# ruff: noqa: E501
# Browser extraction scripts are intentionally kept as literal JavaScript strings.
from __future__ import annotations

import asyncio
import copy
import json
import re
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from playwright.async_api import Locator, Page
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from monash_ed_downloader.errors import LoginRequiredError, SyncSafetyError
from monash_ed_downloader.models import Course, sanitise_data
from monash_ed_downloader.utils import safe_filename, write_json_atomic

STORE_SCHEMA_VERSION = 2
THREAD_FIELDS = (
    "id",
    "courseId",
    "number",
    "title",
    "url",
    "author",
    "role",
    "publishedAt",
    "category",
    "content",
    "images",
)
MESSAGE_FIELDS = ("id", "author", "role", "publishedAt", "content", "images")


def empty_store(course: Course) -> dict[str, Any]:
    return {
        "schema_version": STORE_SCHEMA_VERSION,
        "course": {"id": course.id, "title": course.title, "url": course.url, "categories": []},
        "current_tag": 0,
        "last_successful_scrape_at": None,
        "runs": [],
        "threads": [],
    }


def discussion_store_path(course: Course, output_root: Path) -> Path:
    directory = output_root / safe_filename(course.title) / "Discussions"
    return directory / f"{safe_filename(course.title)} - Discussions.json"


def load_store(course: Course, output_root: Path) -> tuple[dict[str, Any], Path]:
    path = discussion_store_path(course, output_root)
    if not path.exists():
        return empty_store(course), path
    value = json.loads(path.read_text(encoding="utf-8"))
    if (
        value.get("schema_version") != STORE_SCHEMA_VERSION
        or str(value.get("course", {}).get("id")) != course.id
        or not isinstance(value.get("threads"), list)
        or not isinstance(value.get("runs"), list)
    ):
        raise SyncSafetyError(f"Course {course.id} has an unsupported Discussions JSON file.")
    return cast(dict[str, Any], value), path


def _copy_fields(source: dict[str, Any], fields: tuple[str, ...]) -> dict[str, Any]:
    return {
        field: copy.deepcopy(source.get(field, [] if field == "images" else "")) for field in fields
    }


def _new_comment(comment: dict[str, Any], tag: int) -> dict[str, Any]:
    return {
        **_copy_fields(comment, MESSAGE_FIELDS),
        "first_seen_tag": tag,
        "last_seen_tag": tag,
        "last_changed_tag": tag,
    }


def _new_answer(answer: dict[str, Any], tag: int) -> dict[str, Any]:
    return {
        **_copy_fields(answer, MESSAGE_FIELDS),
        "accepted": bool(answer.get("accepted")),
        "first_seen_tag": tag,
        "last_seen_tag": tag,
        "last_changed_tag": tag,
        "comments": [_new_comment(item, tag) for item in answer.get("comments", [])],
    }


def _new_thread(thread: dict[str, Any], tag: int) -> dict[str, Any]:
    return {
        **_copy_fields(thread, THREAD_FIELDS),
        "first_seen_tag": tag,
        "last_seen_tag": tag,
        "last_changed_tag": tag,
        "comments": [_new_comment(item, tag) for item in thread.get("comments", [])],
        "answers": [_new_answer(item, tag) for item in thread.get("answers", [])],
    }


def _merge_messages(
    existing: list[dict[str, Any]],
    incoming: list[dict[str, Any]],
    tag: int,
    fields: tuple[str, ...],
    stats: dict[str, int],
    kind: str,
) -> tuple[list[dict[str, Any]], bool]:
    result = copy.deepcopy(existing)
    positions = {str(item.get("id")): index for index, item in enumerate(result)}
    changed = False
    for item in incoming:
        key = str(item.get("id"))
        if key not in positions:
            created = _new_answer(item, tag) if kind == "answer" else _new_comment(item, tag)
            result.append(created)
            positions[key] = len(result) - 1
            stats[f"new_{kind}s"] += 1
            if kind == "answer":
                stats["new_comments"] += len(created.get("comments", []))
            changed = True
            continue
        current = result[positions[key]]
        item_changed = False
        for field in fields:
            next_value = copy.deepcopy(item.get(field, [] if field == "images" else ""))
            if current.get(field) != next_value:
                current[field] = next_value
                item_changed = True
        if kind == "answer":
            accepted = bool(item.get("accepted"))
            if current.get("accepted") != accepted:
                current["accepted"] = accepted
                item_changed = True
            comments, comments_changed = _merge_messages(
                current.get("comments", []),
                item.get("comments", []),
                tag,
                MESSAGE_FIELDS,
                stats,
                "comment",
            )
            current["comments"] = comments
            item_changed = item_changed or comments_changed
        current["last_seen_tag"] = tag
        if item_changed:
            current["last_changed_tag"] = tag
            stats[f"updated_{kind}s"] += 1
            changed = True
    return result, changed


def merge_scrape(
    store: dict[str, Any], result: dict[str, Any], tag: int | None = None
) -> tuple[dict[str, Any], dict[str, int]]:
    next_tag = tag or int(store.get("current_tag", 0)) + 1
    stats = {
        key: 0
        for key in (
            "new_threads",
            "updated_threads",
            "unchanged_threads",
            "new_answers",
            "updated_answers",
            "new_comments",
            "updated_comments",
        )
    }
    threads = copy.deepcopy(store.get("threads", []))
    positions = {str(item.get("id")): index for index, item in enumerate(threads)}
    for incoming in result.get("threads", []):
        key = str(incoming.get("id"))
        if key not in positions:
            created = _new_thread(incoming, next_tag)
            threads.append(created)
            positions[key] = len(threads) - 1
            stats["new_threads"] += 1
            stats["new_answers"] += len(created["answers"])
            stats["new_comments"] += len(created["comments"]) + sum(
                len(a["comments"]) for a in created["answers"]
            )
            continue
        current = threads[positions[key]]
        changed = False
        for field in THREAD_FIELDS:
            next_value = copy.deepcopy(incoming.get(field, [] if field == "images" else ""))
            if current.get(field) != next_value:
                current[field] = next_value
                changed = True
        comments, comments_changed = _merge_messages(
            current.get("comments", []),
            incoming.get("comments", []),
            next_tag,
            MESSAGE_FIELDS,
            stats,
            "comment",
        )
        answers, answers_changed = _merge_messages(
            current.get("answers", []),
            incoming.get("answers", []),
            next_tag,
            MESSAGE_FIELDS,
            stats,
            "answer",
        )
        current["comments"], current["answers"] = comments, answers
        current["last_seen_tag"] = next_tag
        if changed or comments_changed or answers_changed:
            current["last_changed_tag"] = next_tag
            stats["updated_threads"] += 1
        else:
            stats["unchanged_threads"] += 1
    exported_at = result.get("exportedAt") or datetime.now(UTC).isoformat()
    run = {
        "tag": next_tag,
        "type": "scrape",
        "mode": result.get("mode", "full"),
        "scraped_at": exported_at,
        "source": result.get("source", ""),
        "total_threads": len(threads),
        "scanned_threads": len(result.get("threads", [])),
        "list_items_checked": result.get("listedThreadCount", len(result.get("threads", []))),
        **stats,
    }
    merged = {
        **store,
        "schema_version": STORE_SCHEMA_VERSION,
        "course": copy.deepcopy(result.get("course", store.get("course"))),
        "current_tag": next_tag,
        "last_successful_scrape_at": exported_at,
        "runs": [*store.get("runs", []), run],
        "threads": threads,
    }
    return cast(dict[str, Any], sanitise_data(merged)), stats


def build_known_reply_counts(store: dict[str, Any]) -> dict[str, int]:
    return {
        str(thread.get("id")): len(thread.get("comments", []))
        + len(thread.get("answers", []))
        + sum(len(answer.get("comments", [])) for answer in thread.get("answers", []))
        for thread in store.get("threads", [])
    }


async def _click_if_visible(locator: Locator) -> bool:
    if await locator.count() == 0 or not await locator.first.is_visible():
        return False
    await locator.first.click()
    return True


async def _course_info(page: Page, course: Course) -> dict[str, Any]:
    await page.goto(course.url, wait_until="domcontentloaded")
    try:
        await page.locator('[data-testid="appbar-user"]').wait_for(state="visible", timeout=5_000)
    except PlaywrightTimeoutError:
        raise LoginRequiredError("Ed login is required.") from None
    thread_list = page.locator('section[aria-label="Thread list"]')
    await thread_list.wait_for(state="visible", timeout=20_000)
    categories = await page.locator(
        f'a[href*="/courses/{course.id}/discussion?category="]'
    ).evaluate_all(
        'els => [...new Set(els.map(a => new URL(a.href).searchParams.get("category")).filter(Boolean))]'
    )
    return {"id": course.id, "title": course.title, "url": course.url, "categories": categories}


async def _discover_full(page: Page, course_id: str, progress: Callable[[int], None]) -> list[str]:
    selector = f'section[aria-label="Thread list"] a[href*="/courses/{course_id}/discussion/"]'
    try:
        await page.locator(selector).first.wait_for(state="visible", timeout=15_000)
    except PlaywrightTimeoutError:
        # An authenticated course may legitimately have no discussion threads.
        if await page.locator('section[aria-label="Thread list"]').is_visible():
            return []
        raise
    if await _click_if_visible(
        page.get_by_role("button", name=re.compile(r"^Show \d+ more", re.I))
    ):
        await page.wait_for_timeout(500)
    stable, previous = 0, -1
    for _ in range(500):
        count = await page.locator(selector).count()
        progress(count)
        if await _click_if_visible(
            page.get_by_role("button", name=re.compile(r"^Load More$", re.I))
        ):
            await page.wait_for_timeout(700)
        else:
            listbox = page.locator('section[aria-label="Thread list"] [role="listbox"]')
            if await listbox.count():
                await listbox.evaluate(
                    "el => { let x=el; while(x){if(x.scrollHeight>x.clientHeight)x.scrollTop=x.scrollHeight;x=x.parentElement;} }"
                )
                await page.wait_for_timeout(900)
        next_count = await page.locator(selector).count()
        stable = stable + 1 if next_count == previous else 0
        previous = next_count
        if stable >= 3:
            break
    else:
        raise SyncSafetyError("The discussion list did not become stable.")
    return cast(
        list[str],
        await page.locator(selector).evaluate_all(
            "els => [...new Set(els.map(a => a.href).filter(x => /\\/discussion\\/\\d+$/.test(x)))]"
        ),
    )


async def _discover_incremental(
    page: Page, known: dict[str, int], progress: Callable[[int], None]
) -> tuple[list[str], dict[str, Any]]:
    selector = 'section[aria-label="Thread list"] [role="option"]'
    await page.locator(selector).first.wait_for(state="visible", timeout=15_000)
    processed: set[str] = set()
    new_urls: list[str] = []
    changed_urls: list[str] = []
    recent_urls: list[str] = []
    known_streak = checked = stable = 0
    previous_count = -1
    boundary = reached_end = False
    script = """els => els.flatMap(o => { const a=o.querySelector('a[href*=\"/discussion/\"]'); const href=a?.href||''; const id=href.match(/\\/discussion\\/(\\d+)$/)?.[1]; if(!id)return []; let replies=0; for(const e of o.querySelectorAll('[aria-label=\"Replies\"],[title=\"Replies\"]')){const m=(e.textContent||'').match(/\\d+/);if(m)replies=Number(m[0]);} return [{id,href,replyCount:replies,pinned:Boolean(o.querySelector('[aria-label=\"Pinned\"],[title=\"Pinned\"]'))}];})"""
    while not boundary and not reached_end:
        entries = cast(list[dict[str, Any]], await page.locator(selector).evaluate_all(script))
        for entry in entries:
            key = str(entry["id"])
            if key in processed:
                continue
            processed.add(key)
            checked += 1
            if key not in known:
                new_urls.append(str(entry["href"]))
                if not entry["pinned"]:
                    known_streak = 0
            else:
                if int(entry["replyCount"]) != known[key]:
                    changed_urls.append(str(entry["href"]))
                if not entry["pinned"] and len(recent_urls) < 5:
                    recent_urls.append(str(entry["href"]))
                if not entry["pinned"]:
                    known_streak += 1
            if not entry["pinned"] and known_streak >= 25:
                boundary = True
                break
        progress(checked)
        if boundary:
            break
        if await _click_if_visible(
            page.get_by_role("button", name=re.compile(r"^Load More$", re.I))
        ):
            await page.wait_for_timeout(500)
            stable = 0
            continue
        option_count = await page.locator(selector).count()
        stable = stable + 1 if option_count == previous_count else 0
        previous_count = option_count
        reached_end = stable >= 2
        if not reached_end:
            await page.wait_for_timeout(500)
    urls = list(dict.fromkeys([*new_urls, *changed_urls, *recent_urls]))
    return urls, {"boundaryReached": boundary, "reachedEnd": reached_end, "checkedCount": checked}


async def _parse_thread(page: Page, url: str, course_id: str) -> dict[str, Any]:
    await page.goto(url, wait_until="domcontentloaded")
    section = page.locator('section[aria-label="Thread"]')
    await section.locator('[data-testid="thread"]').wait_for(state="visible", timeout=20_000)
    script = """(root,input)=>{const clean=(e,remove='')=>{if(!e)return '';const c=e.cloneNode(true);c.querySelectorAll('.immersive-translate-target-wrapper').forEach(n=>n.remove());if(remove)c.querySelectorAll(remove).forEach(n=>n.remove());return(c.innerText||c.textContent||'').replace(/\\u00a0/g,' ').replace(/[ \\t]+\\n/g,'\\n').replace(/\\n[ \\t]+/g,'\\n').replace(/\\n{3,}/g,'\\n\\n').trim()};const images=e=>e?[...new Set([...e.querySelectorAll('img[src]')].map(i=>i.src).filter(x=>/^https?:/i.test(x)))]:[];const comment=c=>{const x=c.querySelector('.discom-content');return{id:c.getAttribute('data-comment-id')||'',author:clean(c.querySelector('.author-name')),role:clean(c.querySelector('.user-role-label')),publishedAt:c.querySelector('time[datetime]')?.getAttribute('datetime')||'',content:clean(x),images:images(x)}};const t=root.querySelector('[data-testid=\"thread\"]');const title=t.querySelector('h2.disthrb-title');const body=t.querySelector(':scope > .disthrb-body-layout [data-testid=\"content\"]');const number=title?.querySelector('.disthrb-number')?.getAttribute('aria-label')||'';const answers=[...root.querySelectorAll('[data-testid=\"answer\"]')].map(a=>{const x=a.querySelector(':scope > .disthrb-body-layout [data-testid=\"content\"]');return{id:a.getAttribute('data-comment-id')||'',author:clean(a.querySelector('.author-name')),role:clean(a.querySelector('.user-role-label')),publishedAt:a.querySelector('time[datetime]')?.getAttribute('datetime')||'',accepted:Boolean(a.querySelector('[data-testid=\"answer-accept-button\"].active')),content:clean(x),images:images(x),comments:[...a.querySelectorAll('[data-testid=\"comment\"]')].map(comment)}});return{id:input.url.split('/').pop()||'',courseId:input.courseId,number:number.match(/\\d+/)?.[0]||'',title:clean(title,'.disthrb-number'),url:input.url,author:clean(t.querySelector('.author-name')),role:clean(t.querySelector('.user-role-label')),publishedAt:t.querySelector('time[datetime]')?.getAttribute('datetime')||'',category:clean(t.querySelector('.disthrb-category')),content:clean(body),images:images(body),comments:[...t.querySelectorAll('[data-testid=\"comment\"]')].map(comment),answers}}"""
    return cast(dict[str, Any], await section.evaluate(script, {"url": url, "courseId": course_id}))


async def sync_discussions(
    page: Page,
    course: Course,
    output_root: Path,
    *,
    force_full: bool = False,
    delay_ms: int = 100,
    progress: Callable[[str], None] = lambda _message: None,
) -> tuple[Path, dict[str, int]]:
    store, path = load_store(course, output_root)
    next_tag = int(store["current_tag"]) + 1
    full = int(store["current_tag"]) == 0 or force_full or next_tag % 10 == 0
    course_info = await _course_info(page, course)
    if full:
        urls = await _discover_full(
            page, course.id, lambda count: progress(f"Checking discussion list: {count}")
        )
        discovery: dict[str, Any] | None = None
    else:
        urls, discovery = await _discover_incremental(
            page,
            build_known_reply_counts(store),
            lambda count: progress(f"Checking discussion list: {count}"),
        )
    threads: list[dict[str, Any]] = []
    for index, url in enumerate(urls, 1):
        progress(f"Reading thread {index}/{len(urls)}")
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                threads.append(await _parse_thread(page, url, course.id))
                last_error = None
                break
            except Exception as error:  # noqa: BLE001 - retry browser extraction failures
                last_error = error
                if attempt < 2:
                    await page.wait_for_timeout(700 * (attempt + 1))
        if last_error is not None:
            raise SyncSafetyError(
                f"Thread {url.rsplit('/', 1)[-1]} failed after three attempts."
            ) from last_error
        if delay_ms and index < len(urls):
            await asyncio.sleep(delay_ms / 1000)
    if discovery and not discovery["boundaryReached"] and not discovery["reachedEnd"]:
        raise SyncSafetyError("No reliable incremental boundary was found.")
    previous_total = max([0, *(int(run.get("total_threads", 0)) for run in store["runs"])])
    if full and previous_total >= 10 and len(threads) < int(previous_total * 0.8):
        raise SyncSafetyError("The full scrape found substantially fewer threads than before.")
    result = {
        "mode": "full" if full else "incremental",
        "exportedAt": datetime.now(UTC).isoformat(),
        "source": course.url,
        "course": course_info,
        "threads": threads,
        "listedThreadCount": discovery["checkedCount"] if discovery else len(threads),
    }
    merged, stats = merge_scrape(store, result, next_tag)
    write_json_atomic(path, merged)
    return path, stats
