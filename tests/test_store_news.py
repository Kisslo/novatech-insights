import csv
import io
import json
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


@pytest.fixture
def fake_supabase(monkeypatch):
    monkeypatch.setattr(store_news, "load_dotenv", lambda *args: None)
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_KEY", "test-key")

    def block_network(*args, **kwargs):
        pytest.fail("Unexpected network request")

    monkeypatch.setattr(store_news, "urlopen", block_network)


def test_upload_batches_and_duplicate_counts(fake_supabase, monkeypatch, capsys):
    articles = [
        make_article(link=f"https://example.com/news/{index}") for index in range(205)
    ]
    batches = []

    def fake_urlopen(request, timeout):
        assert request.full_url == (
            "https://example.supabase.co/rest/v1/news?on_conflict=link&select=id"
        )
        assert request.get_method() == "POST"
        assert timeout == 30

        headers = {name.lower(): value for name, value in request.header_items()}
        assert headers["apikey"] == "test-key"
        assert headers["content-type"] == "application/json"
        assert "resolution=ignore-duplicates" in headers["prefer"]

        batch = json.loads(request.data.decode("utf-8"))
        batches.append(batch)

        # Simulate one existing link in each batch.
        saved = [{"id": index} for index in range(len(batch) - 1)]
        return io.BytesIO(json.dumps(saved).encode("utf-8"))

    monkeypatch.setattr(store_news, "urlopen", fake_urlopen)

    store_news.upload_articles(articles)

    assert [len(batch) for batch in batches] == [100, 100, 5]
    assert [article for batch in batches for article in batch] == articles

    output = capsys.readouterr().out
    assert "New articles inserted: 202" in output
    assert "Existing links skipped: 3" in output


def test_empty_upload_makes_no_request(fake_supabase, capsys):
    store_news.upload_articles([])

    assert "No valid articles to upload." in capsys.readouterr().out


@pytest.mark.parametrize("variable", ["SUPABASE_URL", "SUPABASE_KEY"])
def test_missing_configuration_makes_no_request(fake_supabase, monkeypatch, variable):
    monkeypatch.delenv(variable)

    with pytest.raises(ValueError, match="Missing SUPABASE"):
        store_news.upload_articles([make_article()])


def test_failed_batch_stops_further_requests(fake_supabase, monkeypatch):
    articles = [
        make_article(link=f"https://example.com/news/{index}") for index in range(205)
    ]
    calls = []

    def fake_urlopen(request, timeout):
        calls.append(request)

        if len(calls) == 2:
            raise store_news.HTTPError(
                request.full_url,
                503,
                "Service unavailable",
                None,
                None,
            )

        return io.BytesIO(b'[{"id": 1}]')

    monkeypatch.setattr(store_news, "urlopen", fake_urlopen)

    with pytest.raises(RuntimeError, match="HTTP 503"):
        store_news.upload_articles(articles)

    assert len(calls) == 2


def test_connection_error_explains_safe_rerun(fake_supabase, monkeypatch):
    def fake_urlopen(request, timeout):
        raise store_news.URLError("Connection unavailable")

    monkeypatch.setattr(store_news, "urlopen", fake_urlopen)

    with pytest.raises(RuntimeError, match="Rerunning skips existing links"):
        store_news.upload_articles([make_article()])
