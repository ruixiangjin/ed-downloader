from monash_ed_downloader.models import Course, CourseStatus, sanitise_url


def test_course_code_is_discovered_from_title() -> None:
    course = Course("10001", "DEMO1001 Sample Course", "https://example.test", CourseStatus.CURRENT)
    assert course.code == "DEMO1001"


def test_sensitive_query_values_are_removed() -> None:
    result = sanitise_url("https://example.test/file?token=secret&x=1&X-Amz-Signature=bad")
    assert result == "https://example.test/file?x=1"
