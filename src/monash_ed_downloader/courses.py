from __future__ import annotations

import re
from collections.abc import Iterable

from bs4 import BeautifulSoup, Tag
from playwright.async_api import Page
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from monash_ed_downloader.errors import CourseNotFoundError, LoginRequiredError
from monash_ed_downloader.models import Course, CourseStatus

COURSE_PATH = re.compile(r"^/[^/]+/courses/(\d+)(?:/(?:discussion|lessons))?/?$")


def _courses_from_container(
    container: Tag, *, base_url: str, region: str, status: CourseStatus, archive_group: str | None
) -> list[Course]:
    courses: list[Course] = []
    seen: set[str] = set()
    for anchor in container.select("a[href]"):
        match = COURSE_PATH.match(str(anchor.get("href", "")))
        if not match or match.group(1) in seen:
            continue
        course_id = match.group(1)
        seen.add(course_id)
        title = " ".join(anchor.stripped_strings).strip() or f"Course {course_id}"
        courses.append(
            Course(
                id=course_id,
                title=title,
                url=f"{base_url}/{region}/courses/{course_id}/discussion",
                status=status,
                archive_group=archive_group,
            )
        )
    return courses


def parse_dashboard_html(html: str, *, base_url: str, region: str) -> list[Course]:
    soup = BeautifulSoup(html, "html.parser")
    root = soup.select_one(".dash-container")
    if root is None:
        raise ValueError("ED Dashboard course container was not found.")

    archived = False
    archive_group: str | None = None
    courses: list[Course] = []
    found_boundary = False
    for child in root.find_all(recursive=False):
        text = child.get_text(" ", strip=True)
        raw_classes = child.get("class")
        classes = set(str(item) for item in raw_classes) if isinstance(raw_classes, list) else set()
        if "dash-header" in classes and text.casefold() == "archived":
            archived = True
            found_boundary = True
            continue
        if archived and child.name == "h2":
            archive_group = text or "Archived"
            continue
        if "dash-courses" in classes:
            courses.extend(
                _courses_from_container(
                    child,
                    base_url=base_url.rstrip("/"),
                    region=region,
                    status=CourseStatus.ARCHIVED if archived else CourseStatus.CURRENT,
                    archive_group=archive_group if archived else None,
                )
            )
    if not courses:
        raise ValueError("No ED courses were found on the Dashboard.")
    if len([node for node in root.select(":scope > .dash-courses")]) > 1 and not found_boundary:
        for course in courses:
            course.status = CourseStatus.UNCLASSIFIED
    return courses


class CourseCatalog:
    def __init__(self, page: Page, *, base_url: str, region: str) -> None:
        self.page = page
        self.base_url = base_url.rstrip("/")
        self.region = region

    async def list_courses(self) -> list[Course]:
        await self.page.goto(
            f"{self.base_url}/{self.region}/dashboard",
            wait_until="domcontentloaded",
        )
        try:
            await self.page.locator('[data-testid="appbar-user"]').wait_for(
                state="visible", timeout=5_000
            )
        except PlaywrightTimeoutError:
            raise LoginRequiredError("Ed login is required. Run `ed-downloader login`.") from None
        return parse_dashboard_html(
            await self.page.content(), base_url=self.base_url, region=self.region
        )

    @staticmethod
    def resolve(courses: Iterable[Course], selector: str) -> Course:
        normalised = selector.strip().casefold()
        matches = [
            course
            for course in courses
            if course.id == selector.strip() or course.code.casefold() == normalised
        ]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            raise CourseNotFoundError(
                f"More than one course matches {selector}. Use the numeric Ed course ID."
            )
        raise CourseNotFoundError(f"No accessible ED course matches {selector}.")
