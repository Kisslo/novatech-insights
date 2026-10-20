import csv
from datetime import UTC, datetime, timedelta, timezone

import pytest

from src import store_news


@pytest.fixture
def csv_file(tmp_path, monkeypatch):
    path = tmp_path / "news.csv"
    monkeypatch.setattr(store_news, "CSV_FILE", path)
    return path


def write_articles(path, articles):
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=store_news.FIELDS)
        writer.writeheader()
        writer.writerows(articles)


def make_article(**changes):
    article = {
        "title": "Example news",
        "link": "https://example.com/news",
        "source": "Example Source",
        "published": (datetime.now(UTC) - timedelta(days=1)).isoformat(),
        "subject": "",
        "description": "",
    }
    article.update(changes)
    return article


def test_accepts_empty_subject_and_description(csv_file):
    write_articles(csv_file, [make_article()])

    articles = store_news.load_articles()

    assert len(articles) == 1
    assert articles[0]["subject"] == ""
    assert articles[0]["description"] == ""


@pytest.mark.parametrize("field", ["title", "link", "source"])
def test_rejects_blank_required_fields(csv_file, field):
    write_articles(csv_file, [make_article(**{field: "   "})])

    assert store_news.load_articles() == []


@pytest.mark.parametrize(
    "published",
    [
        "",
        "not a date",
        "2026-02-30T12:00:00Z",
        "2026-10-19T12:00:00",
    ],
)
def test_rejects_invalid_or_timezone_free_dates(csv_file, published):
    write_articles(csv_file, [make_article(published=published)])

    assert store_news.load_articles() == []


@pytest.mark.parametrize("days_ago", [8, -1])
def test_rejects_old_or_future_articles(csv_file, days_ago):
    published = (datetime.now(UTC) - timedelta(days=days_ago)).isoformat()
    write_articles(csv_file, [make_article(published=published)])

    assert store_news.load_articles() == []


def test_converts_offset_timestamp_to_utc(csv_file):
    instant = (datetime.now(UTC) - timedelta(days=1)).replace(microsecond=0)
    offset = instant.astimezone(timezone(timedelta(hours=2)))
    write_articles(
        csv_file,
        [make_article(published=offset.isoformat())],
    )

    articles = store_news.load_articles()

    expected = instant.isoformat().replace("+00:00", "Z")
    assert articles[0]["published"] == expected


def test_duplicate_links_keep_first_valid_record(csv_file):
    write_articles(
        csv_file,
        [
            make_article(title="First"),
            make_article(
                title="Second",
                link="  https://example.com/news  ",
            ),
        ],
    )

    articles = store_news.load_articles()

    assert len(articles) == 1
    assert articles[0]["title"] == "First"


def test_rejects_unexpected_csv_columns(csv_file):
    csv_file.write_text("title,link\nExample,https://example.com\n")

    with pytest.raises(ValueError, match="Unexpected CSV columns"):
        store_news.load_articles()
