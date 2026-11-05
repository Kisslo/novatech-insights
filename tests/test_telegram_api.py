import io
import json
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

from telegram_api import app
from telegram_format import MAX_CALLBACK_BYTES, MAX_MESSAGE_CHARS

API_KEY = "test-key-that-is-long-enough-1234567890"
SUPABASE_KEY = "sb_secret_never_in_answers"

client = TestClient(app)


@pytest.fixture(autouse=True)
def api_env(monkeypatch):
    monkeypatch.setenv("TELEGRAM_API_KEY", API_KEY)
    monkeypatch.setenv("TELEGRAM_SOURCE", "fixture")
    monkeypatch.delenv("TOPICS_OVERVIEW_VIEW", raising=False)
    monkeypatch.delenv("TOPICS_ARTICLES_VIEW", raising=False)


def get_top(n=None, key=API_KEY):
    headers = {"X-API-Key": key} if key is not None else {}
    params = {"n": n} if n is not None else {}
    return client.get("/telegram/top", headers=headers, params=params)


# -------------------- API key


def test_missing_key_gives_401():
    response = get_top(key=None)
    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid or missing API key"}


def test_wrong_key_gives_401():
    assert get_top(key=API_KEY + "x").status_code == 401
    assert get_top(key="").status_code == 401


@pytest.mark.parametrize("configured", ["", "too-short"])
def test_missing_or_short_key_in_env_refuses_everything(monkeypatch, configured):
    monkeypatch.setenv("TELEGRAM_API_KEY", configured)
    response = get_top(key=configured)
    assert response.status_code == 503
    assert response.json() == {"detail": "API key is not configured"}


def test_docs_pages_are_turned_off():
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert client.get(path).status_code == 404


# -------------------- fixture source


def test_fixture_gives_top_five_labelled_topics():
    response = get_top()

    assert response.status_code == 200
    body = response.json()
    assert body["source"] == "fixture"
    assert body["requested"] == 5
    assert body["count"] == 5
    assert [t["topic_id"] for t in body["topics"]] == [101, 102, 103, 104, 105]
    assert [t["rank"] for t in body["topics"]] == [1, 2, 3, 4, 5]
    assert body["skipped"] == []


def test_messages_are_ready_for_telegram():
    for message in get_top().json()["topics"]:
        assert message["parse_mode"] == "HTML"
        assert len(message["text"]) <= MAX_MESSAGE_CHARS
        assert [b["text"] for b in message["buttons"]] == ["Skriv", "Skippa"]
        assert [b["callback_data"] for b in message["buttons"]] == [
            f"write:{message['topic_id']}",
            f"skip:{message['topic_id']}",
        ]
        for button in message["buttons"]:
            assert len(button["callback_data"].encode("utf-8")) <= MAX_CALLBACK_BYTES
    # "&" in the label of topic 102 is escaped
    second = get_top().json()["topics"][1]["text"]
    assert "fakturor &amp; bokslut" in second


def test_unlabelled_topic_is_left_out():
    body = get_top(n=20).json()
    assert body["count"] == 5
    assert 106 not in [t["topic_id"] for t in body["topics"]]


@pytest.mark.parametrize("n", [0, 21, "five"])
def test_invalid_n_gives_422(n):
    assert get_top(n=n).status_code == 422


def test_unknown_source_gives_500_without_details(monkeypatch):
    monkeypatch.setenv("TELEGRAM_SOURCE", "sheets")
    response = get_top()
    assert response.status_code == 500
    assert "sheets" not in response.text


# -------------------- Supabase source (the REST API is always mocked)


def overview_row(topic_id, score, **changes):
    row = {
        "id": topic_id,
        "score": score,
        "article_count": 3,
        "source_count": 2,
        "label": f"Rubrik {topic_id}",
        "why_relevant_sv": f"Motivering {topic_id}.",
        "llm_relevance": 4,
    }
    row.update(changes)
    return row


def article_row(topic_id, **changes):
    row = {
        "topic_id": topic_id,
        "news_id": topic_id * 10,
        "title": f"Titel {topic_id}",
        "source": "Källa",
        "link": f"https://example.com/{topic_id}",
        "description": "",
        "rank_in_topic": 1,
    }
    row.update(changes)
    return row


@pytest.fixture
def supabase(monkeypatch):
    """Mock Supabase. Set .overview and .articles, read .requests."""
    monkeypatch.setenv("TELEGRAM_SOURCE", "supabase")
    monkeypatch.setenv("SUPABASE_URL", "https://project.supabase.co")
    monkeypatch.setenv("SUPABASE_KEY", SUPABASE_KEY)

    class Fake:
        overview: list = []
        articles: list = []
        error: Exception | None = None
        requests: list = []

    fake = Fake()
    fake.requests = []

    def call(request, timeout):
        fake.requests.append(request)
        if fake.error is not None:
            raise fake.error
        query = parse_qs(urlparse(request.full_url).query)
        view = urlparse(request.full_url).path.rsplit("/", 1)[-1]
        if view == "topic_overview":
            offset, limit = int(query["offset"][0]), int(query["limit"][0])
            rows = fake.overview[offset : offset + limit]
        else:
            ids = {int(i) for i in query["topic_id"][0][4:-1].split(",")}
            rows = [row for row in fake.articles if row["topic_id"] in ids]
        return io.BytesIO(json.dumps(rows).encode("utf-8"))

    monkeypatch.setattr("label_topics.urlopen", call)
    return fake


def test_supabase_reads_only_labelled_topics(supabase):
    supabase.overview = [overview_row(i, 1 - i / 100) for i in range(1, 8)]
    supabase.articles = [article_row(i) for i in range(1, 8)]

    body = get_top().json()

    assert body["source"] == "supabase"
    assert [t["topic_id"] for t in body["topics"]] == [1, 2, 3, 4, 5]
    query = parse_qs(urlparse(supabase.requests[0].full_url).query)
    assert query["label"] == ["not.is.null"]
    assert query["order"] == ["score.desc,id.asc"]
    for request in supabase.requests:
        assert request.get_method() == "GET"
        assert request.get_header("Apikey") == SUPABASE_KEY
        assert not request.has_header("Authorization")


def test_skipped_topics_do_not_make_the_answer_shorter_than_n(supabase):
    supabase.overview = [overview_row(i, 1 - i / 100) for i in range(1, 9)]
    # Topic 2 has an article without link; topic 4 has an invalid llm_relevance
    supabase.overview[3]["llm_relevance"] = 9
    supabase.articles = [
        article_row(i, link="" if i == 2 else f"https://example.com/{i}")
        for i in range(1, 9)
    ]

    body = get_top().json()

    assert [t["topic_id"] for t in body["topics"]] == [1, 3, 5, 6, 7]
    assert [t["rank"] for t in body["topics"]] == [1, 2, 3, 4, 5]
    assert [s["topic_id"] for s in body["skipped"]] == [2, 4]
    assert body["skipped"][0]["reason"] == "article in topic 2 has no 'link'"


def test_supabase_error_gives_502_without_secrets(supabase):
    supabase.error = HTTPError("u", 401, "Unauthorized", {}, None)

    response = get_top()

    assert response.status_code == 502
    assert response.json() == {"detail": "Could not read topics"}
    assert SUPABASE_KEY not in response.text
    assert "SUPABASE" not in response.text


def test_answers_never_contain_keys(supabase):
    supabase.overview = [overview_row(1, 0.9)]
    supabase.articles = [article_row(1)]

    response = get_top()

    assert response.status_code == 200
    assert API_KEY not in response.text
    assert SUPABASE_KEY not in response.text


def test_many_invalid_topics_still_give_five_messages(supabase):
    # 12 topics at the top cannot be sent: 6 lack a link, 6 have a bad rating
    supabase.overview = [overview_row(i, 1 - i / 1000) for i in range(1, 31)]
    for row in supabase.overview[6:12]:
        row["llm_relevance"] = 9
    supabase.articles = [
        article_row(i, link="" if i <= 6 else f"https://example.com/{i}")
        for i in range(1, 31)
    ]

    body = get_top().json()

    assert body["count"] == 5
    assert [t["topic_id"] for t in body["topics"]] == [13, 14, 15, 16, 17]
    assert [s["topic_id"] for s in body["skipped"]] == list(range(1, 13))
