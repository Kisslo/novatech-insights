import json
import sys
from urllib.error import HTTPError, URLError

import numpy as np
import pytest

import src.group_news as grouping


@pytest.fixture(autouse=True)
def fake_connection(monkeypatch):
    monkeypatch.setattr(grouping, "SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setattr(grouping, "SUPABASE_KEY", "sb_secret_test123")

    def block_network(*args, **kwargs):
        pytest.fail("Unexpected network request")

    monkeypatch.setattr(grouping, "urlopen", block_network)


def mock_response(monkeypatch, body):
    requests = []

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return body

    def fake_urlopen(request, timeout):
        requests.append(request)
        assert timeout == 60
        return FakeResponse()

    monkeypatch.setattr(grouping, "urlopen", fake_urlopen)
    return requests


def test_save_group_sends_all_distinct_article_ids(monkeypatch):
    requests = mock_response(monkeypatch, b"42")
    group = {"articles": [{"id": news_id} for news_id in [9, 2, 7, 4, 6, 3, 2]]}

    result = grouping.save_group(group)

    assert result == 42
    assert len(requests) == 1

    request = requests[0]
    assert request.full_url == (
        "https://example.supabase.co/rest/v1/rpc/save_topic_group"
    )
    assert request.get_method() == "POST"
    assert request.get_header("Apikey") == "sb_secret_test123"
    assert not request.has_header("Authorization")
    assert request.get_header("Content-type") == "application/json"
    assert json.loads(request.data) == {"p_news_ids": [2, 3, 4, 6, 7, 9]}


@pytest.mark.parametrize(
    "articles",
    [
        None,
        [],
        "invalid",
        [None, {"id": 2}],
        [{}, {"id": 2}],
        [{"id": True}, {"id": 2}],
        [{"id": "1"}, {"id": 2}],
        [{"id": 1.5}, {"id": 2}],
        [{"id": 0}, {"id": 2}],
        [{"id": -1}, {"id": 2}],
        [{"id": 9223372036854775808}, {"id": 2}],
        [{"id": 1}],
        [{"id": 1}, {"id": 1}],
    ],
)
def test_save_group_rejects_invalid_articles_before_request(articles):
    with pytest.raises(ValueError):
        grouping.save_group({"articles": articles})


@pytest.mark.parametrize("setting", ["SUPABASE_URL", "SUPABASE_KEY"])
def test_save_group_requires_connection_settings(monkeypatch, setting):
    monkeypatch.setattr(grouping, setting, "")

    with pytest.raises(ValueError, match="missing"):
        grouping.save_group({"articles": [{"id": 1}, {"id": 2}]})


@pytest.mark.parametrize("status", [401, 403, 404, 500])
def test_save_group_reports_http_errors_without_exposing_key(monkeypatch, status):
    def fail_request(request, timeout):
        raise HTTPError(
            request.full_url,
            status,
            "Sensitive detail: sb_secret_test123",
            {},
            None,
        )

    monkeypatch.setattr(grouping, "urlopen", fail_request)

    with pytest.raises(RuntimeError) as error:
        grouping.save_group({"articles": [{"id": 1}, {"id": 2}]})

    assert f"HTTP {status}" in str(error.value)
    assert "Earlier groups may already be saved" in str(error.value)
    assert "sb_secret_test123" not in str(error.value)


@pytest.mark.parametrize(
    "failure",
    [
        URLError("connection failed"),
        TimeoutError("timed out"),
        OSError("connection interrupted"),
    ],
)
def test_save_group_reports_uncertain_network_outcome(monkeypatch, failure):
    def fail_request(request, timeout):
        raise failure

    monkeypatch.setattr(grouping, "urlopen", fail_request)

    with pytest.raises(RuntimeError, match="may already be saved"):
        grouping.save_group({"articles": [{"id": 1}, {"id": 2}]})


@pytest.mark.parametrize(
    "body",
    [
        b"not-json",
        b"\xff",
        b"null",
        b"true",
        b"0",
        b"-1",
        b'"42"',
        b"1.5",
        b"[]",
        b"{}",
    ],
)
def test_save_group_rejects_invalid_responses(monkeypatch, body):
    mock_response(monkeypatch, body)

    with pytest.raises(RuntimeError, match="may already be saved"):
        grouping.save_group({"articles": [{"id": 1}, {"id": 2}]})


def prepare_main(monkeypatch, groups, arguments):
    articles = [
        {"id": 1, "title": "Article A", "description": ""},
        {"id": 2, "title": "Article B", "description": ""},
    ]

    class FakeModel:
        def encode(self, texts, **kwargs):
            return np.array([[1.0, 0.0], [0.9, 0.1]])

    monkeypatch.setattr(sys, "argv", ["group_news.py", *arguments])
    monkeypatch.setattr(grouping, "fetch_articles", lambda: articles)
    monkeypatch.setattr(grouping, "deduplicate_articles", lambda items: items)
    monkeypatch.setattr(grouping, "SentenceTransformer", lambda name: FakeModel())
    monkeypatch.setattr(grouping, "build_groups", lambda items, embeddings: groups)
    monkeypatch.setattr(grouping, "print_groups", lambda items: None)


def test_main_does_not_save_by_default(monkeypatch, capsys):
    groups = [{"articles": [{"id": 1}, {"id": 2}]}]
    prepare_main(monkeypatch, groups, [])

    def unexpected_save(group):
        pytest.fail("Saving must require --save")

    monkeypatch.setattr(grouping, "save_group", unexpected_save)

    grouping.main()

    assert "Read-only run. No groups saved." in capsys.readouterr().out


def test_main_save_processes_all_groups_beyond_display_limit(monkeypatch):
    groups = [
        {"articles": [{"id": 2 * index + 1}, {"id": 2 * index + 2}]}
        for index in range(grouping.TOP_GROUPS + 1)
    ]
    prepare_main(monkeypatch, groups, ["--save"])
    saved = []

    def fake_save(group):
        saved.append(group)
        return len(saved)

    monkeypatch.setattr(grouping, "save_group", fake_save)

    grouping.main()

    assert saved == groups


def test_main_stops_after_save_failure(monkeypatch):
    groups = [
        {"articles": [{"id": 1}, {"id": 2}]},
        {"articles": [{"id": 3}, {"id": 4}]},
        {"articles": [{"id": 5}, {"id": 6}]},
    ]
    prepare_main(monkeypatch, groups, ["--save"])
    attempted = []

    def fake_save(group):
        attempted.append(group)
        if len(attempted) == 2:
            raise RuntimeError("Connection interrupted")
        return 42

    monkeypatch.setattr(grouping, "save_group", fake_save)

    with pytest.raises(SystemExit, match="Stopped at group 2/3"):
        grouping.main()

    assert attempted == groups[:2]


def test_main_with_no_groups_makes_no_save_requests(monkeypatch):
    prepare_main(monkeypatch, [], ["--save"])

    def unexpected_save(group):
        pytest.fail("There are no groups to save")

    monkeypatch.setattr(grouping, "save_group", unexpected_save)

    grouping.main()
