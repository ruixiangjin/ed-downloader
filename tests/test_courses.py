from monash_ed_downloader.courses import CourseCatalog, parse_dashboard_html
from monash_ed_downloader.models import CourseStatus

HTML = """
<div class="dash-container">
  <div class="dash-header">Courses</div>
  <div class="dash-courses">
    <a href="/au/courses/10001/discussion">DEMO1001 Sample Course</a>
    <a href="/au/courses/10002">DEMO1002 Another Course</a>
  </div>
  <div class="dash-header">Archived</div>
  <h2 class="dash-subheading">2026 SEMESTER 1</h2>
  <div class="dash-courses">
    <a href="/au/courses/29579/discussion">FIT1008 S1 2026</a>
  </div>
</div>
"""


def test_dashboard_courses_are_split_at_archived_heading() -> None:
    courses = parse_dashboard_html(HTML, base_url="https://edstem.org", region="au")
    assert [course.id for course in courses] == ["10001", "10002", "29579"]
    assert courses[0].status is CourseStatus.CURRENT
    assert courses[2].status is CourseStatus.ARCHIVED
    assert courses[2].archive_group == "2026 SEMESTER 1"


def test_catalog_resolves_code_or_id() -> None:
    courses = parse_dashboard_html(HTML, base_url="https://edstem.org", region="au")
    assert CourseCatalog.resolve(courses, "DEMO1001").id == "10001"
    assert CourseCatalog.resolve(courses, "29579").code == "FIT1008"
