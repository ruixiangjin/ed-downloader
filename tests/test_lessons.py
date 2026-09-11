from monash_ed_downloader.download import content_disposition_filename, is_media
from monash_ed_downloader.lessons import xml_to_markdown
from monash_ed_downloader.selection import parse_group_selection


def test_ed_xml_becomes_readable_markdown() -> None:
    value = '<document><heading level="2">Setup</heading><paragraph>Read <link href="https://example.test">this</link>.</paragraph><list><list-item><paragraph>First</paragraph></list-item></list></document>'
    assert xml_to_markdown(value) == "## Setup\nRead [this](https://example.test).\n- First"


def test_media_is_link_only_by_mime_or_extension() -> None:
    assert is_media("https://static.test/no-extension", "image/png")
    assert is_media("https://static.test/video.mp4")
    assert not is_media("https://static.test/notes.pdf", "application/pdf")


def test_content_disposition_prefers_utf8_filename() -> None:
    assert (
        content_disposition_filename("inline; filename=old.pdf; filename*=UTF-8''week%201.pdf")
        == "week 1.pdf"
    )


def test_group_selection_supports_ranges_and_chinese_punctuation() -> None:
    assert parse_group_selection("1，3～5", [1, 2, 3, 4, 5]) == [1, 3, 4, 5]
