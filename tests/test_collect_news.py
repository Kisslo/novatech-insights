from datetime import UTC, datetime

import pytest

from src.collect_news import clean_description, format_date, parse_date


@pytest.mark.parametrize(
    "value",
    [
        "Sun, 18 Oct 2026 14:00:00 +0200",
        "2026-10-18T14:00:00+02:00",
        "2026-10-18T12:00:00Z",
        "2026-10-18T12:00:00+00:00",
        "  2026-10-18T12:00:00Z  ",
    ],
)
def test_parse_date_converts_valid_date_to_utc(value):
    result = parse_date(value)

    expected = datetime(2026, 10, 18, 12, 0, 0, tzinfo=UTC)
    assert result is not None
    assert result == expected
    assert result.tzinfo is UTC


@pytest.mark.parametrize(
    "value",
    [
        None,
        "",
        "   ",
        "not a date",
        "2026-02-30T12:00:00Z",
        "2026-13-18T12:00:00Z",
        "2026-10-18T14:00:00",
        "Sun, 18 Oct 2026 14:00:00",
    ],
)
def test_parse_date_rejects_missing_invalid_or_timezone_free_date(value):
    result = parse_date(value)

    assert result is None


def test_format_date_uses_iso_format_with_utc_marker():
    date = datetime(2026, 10, 18, 12, 30, 45, tzinfo=UTC)

    result = format_date(date)

    assert result == "2026-10-18T12:30:45Z"


def test_format_date_removes_microseconds():
    date = datetime(2026, 10, 18, 12, 30, 45, 123456, tzinfo=UTC)

    result = format_date(date)

    assert result == "2026-10-18T12:30:45Z"


def test_formatted_date_can_be_parsed_again():
    original = datetime(2026, 10, 18, 12, 30, 45, tzinfo=UTC)

    result = parse_date(format_date(original))

    assert result == original


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, ""),
        ("", ""),
        ("   \n\t  ", ""),
        ("Plain text.", "Plain text."),
        ("<p>Hello <strong>world</strong>.</p>", "Hello world."),
        ("<p>First</p><p>Second</p>", "First Second"),
        ("First<br>Second", "First Second"),
        ("AI &amp; data &#8211; news", "AI & data – news"),
        ("  First\n\t second   third  ", "First second third"),
        ("<p>Swedish: åäö ÅÄÖ</p>", "Swedish: åäö ÅÄÖ"),
    ],
)
def test_clean_description_returns_normalized_plain_text(value, expected):
    result = clean_description(value)

    assert result == expected
