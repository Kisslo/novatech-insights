import io
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime
from urllib.parse import parse_qs, urlparse

import pytest

from src import collect_news
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


# -------------------- collection runs and monitoring (#70)

NOW = datetime(2026, 11, 24, 12, 0, 0, tzinfo=UTC)
RECENT = format_datetime(NOW - timedelta(hours=1))
OLD = format_datetime(NOW - timedelta(days=30))


def rss(*items):
    """A small RSS document. Each item is (title, link, pubDate)."""
    body = "".join(
        f"<item><title>{title}</title><link>{link}</link>"
        f"<pubDate>{published}</pubDate></item>"
        for title, link, published in items
    )
    return f"<rss><channel><title>Feed</title>{body}</channel></rss>".encode()


class FakeSupabase:
    """Records pipeline_runs requests and can fail on POST or PATCH."""

    def __init__(self, fail_on=None):
        self.calls = []
        self.fail_on = fail_on

    def __call__(self, url, key, *, method="GET", payload=None):
        self.calls.append((method, url, payload))
        if method == self.fail_on:
            raise RuntimeError("supabase is down")
        if method == "POST":
            return [{"run_id": payload["run_id"]}]
        run_id = parse_qs(urlparse(url).query)["run_id"][0].removeprefix("eq.")
        return [{"run_id": run_id}]

    def finished(self):
        method, url, payload = self.calls[-1]
        assert method == "PATCH"
        assert "status=eq.running" in url
        return payload


@pytest.fixture
def collector(tmp_path, monkeypatch):
    """Point the collector at temporary files and fake feeds."""
    feeds = {}
    opened = []

    def setup(sources, feed_answers, existing=None):
        sources_file = tmp_path / "sources.csv"
        sources_file.write_text(sources, encoding="utf-8")
        output_file = tmp_path / "news.csv"
        if existing is not None:
            output_file.write_text(existing, encoding="utf-8")
        monkeypatch.setattr(collect_news, "SOURCES_FILE", sources_file)
        monkeypatch.setattr(collect_news, "OUTPUT_FILE", output_file)
        feeds.update(feed_answers)
        return output_file

    def fake_urlopen(request, timeout):
        opened.append(request.full_url)
        answer = feeds[request.full_url]
        if isinstance(answer, Exception):
            raise answer
        return io.BytesIO(answer)

    monkeypatch.setattr(collect_news.urllib.request, "urlopen", fake_urlopen)
    setup.opened = opened
    return setup


def run(supabase):
    return collect_news.run_collection(
        url="https://example.test/", key="secret", now=NOW, request=supabase
    )


def test_run_is_created_as_collection_write_run(collector):
    collector(
        "name,feed_url\nA,https://a.test/rss\n",
        {"https://a.test/rss": rss(("One", "https://a.test/1", RECENT))},
    )
    supabase = FakeSupabase()

    result = run(supabase)

    method, url, payload = supabase.calls[0]
    assert method == "POST"
    assert url == "https://example.test/rest/v1/pipeline_runs"
    assert payload["stage"] == "collection"
    assert payload["mode"] == "write"
    assert payload["status"] == "running"
    assert payload["run_id"] == result["run_id"]
    assert payload["started_at"]


def test_failed_feed_and_empty_feed_give_partial(collector, capsys):
    collector(
        "name,feed_url\n"
        "Slow feed,https://example.com/slow.xml\n"
        "Empty feed,https://example.com/empty.xml\n",
        {
            "https://example.com/slow.xml": TimeoutError("timed out"),
            "https://example.com/empty.xml": rss(),
        },
    )
    supabase = FakeSupabase()

    result = run(supabase)

    output = capsys.readouterr().out
    assert "Feed failed: Slow feed (TimeoutError: timed out)" in output
    assert "Feed read successfully: Empty feed (no new articles added)" in output
    assert "Feeds read successfully: 1" in output
    assert "Feeds failed: 1" in output
    assert "Total new articles: 0" in output
    assert result["status"] == "partial"
    finished = supabase.finished()
    assert finished["status"] == "partial"
    assert finished["finished_at"]
    assert finished["metrics"]["feeds_failed"] == 1
    assert finished["metrics"]["feeds_succeeded"] == 1
    assert finished["details"]["failed_feeds"] == {
        "Slow feed": "TimeoutError: timed out"
    }


def test_all_feeds_failing_gives_failed(collector):
    output_file = collector(
        "name,feed_url\nA,https://a.test/rss\nB,https://b.test/rss\n",
        {
            "https://a.test/rss": TimeoutError("timed out"),
            "https://b.test/rss": b"not xml",
        },
    )
    supabase = FakeSupabase()

    result = run(supabase)

    assert result["status"] == "failed"
    finished = supabase.finished()
    assert finished["status"] == "failed"
    assert finished["metrics"]["feeds_attempted"] == 2
    assert finished["metrics"]["feeds_failed"] == 2
    assert set(finished["details"]["failed_feeds"]) == {"A", "B"}
    assert output_file.exists()


def test_working_feeds_without_new_articles_give_no_data(collector):
    existing = (
        "title,link,source,published,subject,description\n"
        f"Known,https://a.test/1,A,{format_date(NOW - timedelta(hours=2))},,\n"
    )
    collector(
        "name,feed_url\nA,https://a.test/rss\n",
        {"https://a.test/rss": rss(("Known", "https://a.test/1", RECENT))},
        existing=existing,
    )
    supabase = FakeSupabase()

    result = run(supabase)

    assert result["status"] == "no_data"
    metrics = supabase.finished()["metrics"]
    assert metrics["articles_new"] == 0
    assert metrics["articles_duplicate"] == 1
    assert metrics["articles_saved"] == 1


def test_success_counts_configured_attempted_rejected_and_duplicates(collector):
    output_file = collector(
        "name,feed_url\nA,https://a.test/rss\nB,https://b.test/rss\nNo URL,\n",
        {
            "https://a.test/rss": rss(
                ("New", "https://a.test/1", RECENT),
                ("Old", "https://a.test/2", OLD),
                ("", "https://a.test/3", RECENT),
            ),
            "https://b.test/rss": rss(("New", "https://a.test/1", RECENT)),
        },
    )
    supabase = FakeSupabase()

    result = run(supabase)

    assert result["status"] == "success"
    metrics = supabase.finished()["metrics"]
    assert metrics["feeds_configured"] == 3
    assert metrics["feeds_attempted"] == 2
    assert metrics["feeds_succeeded"] == 2
    assert metrics["feeds_skipped_missing_url"] == 1
    assert metrics["items_fetched"] == 4
    assert metrics["articles_new"] == 1
    assert metrics["articles_duplicate"] == 1
    assert metrics["articles_rejected_date"] == 1
    assert metrics["articles_rejected_missing_fields"] == 1
    assert metrics["articles_rejected"] == 2
    assert metrics["articles_saved"] == 1
    assert metrics["duration_seconds"] >= 0
    assert "https://a.test/1" in output_file.read_text(encoding="utf-8-sig")


@pytest.mark.parametrize(
    ("sources", "message"),
    [
        (None, "Source list not found"),
        ("name,url\nA,https://a.test/rss\n", "missing columns: feed_url"),
        ("name,feed_url\nA,\n", "has no feed URLs"),
    ],
)
def test_invalid_configuration_gives_failed(collector, tmp_path, sources, message):
    collector("name,feed_url\nA,https://a.test/rss\n", {})
    if sources is None:
        (tmp_path / "sources.csv").unlink()
    else:
        (tmp_path / "sources.csv").write_text(sources, encoding="utf-8")
    supabase = FakeSupabase()

    result = run(supabase)

    assert result["status"] == "failed"
    assert collector.opened == []
    finished = supabase.finished()
    assert finished["status"] == "failed"
    assert message in finished["details"]["run_error"]
    assert finished["metrics"]["feeds_attempted"] == 0


def test_output_save_failure_gives_failed(collector, tmp_path, monkeypatch):
    collector(
        "name,feed_url\nA,https://a.test/rss\n",
        {"https://a.test/rss": rss(("One", "https://a.test/1", RECENT))},
    )
    monkeypatch.setattr(
        collect_news, "OUTPUT_FILE", tmp_path / "missing-folder" / "news.csv"
    )
    supabase = FakeSupabase()

    result = run(supabase)

    assert result["status"] == "failed"
    finished = supabase.finished()
    assert finished["status"] == "failed"
    assert "Could not save" in finished["details"]["run_error"]
    assert not (tmp_path / "missing-folder").exists()


def test_monitoring_start_failure_stops_before_reading_feeds(collector):
    output_file = collector(
        "name,feed_url\nA,https://a.test/rss\n",
        {"https://a.test/rss": rss(("One", "https://a.test/1", RECENT))},
    )

    with pytest.raises(collect_news.PipelineMonitoringError):
        run(FakeSupabase(fail_on="POST"))

    assert collector.opened == []
    assert not output_file.exists()


def test_monitoring_finish_failure_is_reported_after_saving(collector, capsys):
    output_file = collector(
        "name,feed_url\nA,https://a.test/rss\n",
        {"https://a.test/rss": rss(("One", "https://a.test/1", RECENT))},
    )

    result = run(FakeSupabase(fail_on="PATCH"))

    assert result["status"] == "success"
    assert "Could not finish collection run" in result["monitoring_error"]
    assert output_file.exists()
    assert "Collection monitoring error" in capsys.readouterr().err


def test_supabase_settings_are_required():
    with pytest.raises(ValueError, match="SUPABASE_URL and SUPABASE_KEY"):
        collect_news.run_collection(url="", key="", request=FakeSupabase())


@pytest.mark.parametrize(
    ("status", "monitoring_error", "exit_code"),
    [
        ("success", None, 0),
        ("partial", None, 0),
        ("no_data", None, 0),
        ("failed", None, 1),
        ("success", "could not finish", 1),
    ],
)
def test_main_exit_code(monkeypatch, status, monitoring_error, exit_code):
    monkeypatch.setattr(collect_news, "load_dotenv", lambda path: None)
    monkeypatch.setattr(
        collect_news,
        "run_collection",
        lambda **kwargs: {"status": status, "monitoring_error": monitoring_error},
    )

    assert collect_news.main([]) == exit_code


def test_main_returns_1_when_monitoring_cannot_start(monkeypatch):
    def fail(**kwargs):
        raise collect_news.PipelineMonitoringError("no run")

    monkeypatch.setattr(collect_news, "load_dotenv", lambda path: None)
    monkeypatch.setattr(collect_news, "run_collection", fail)

    assert collect_news.main([]) == 1
