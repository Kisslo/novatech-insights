from copy import deepcopy
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlparse

import pytest

import rank_topics_supabase as adapter

CONFIG = {
    "source_weights": {},
    "swedish_sources": {"breakit"},
    "max_breadth_bonus": 1.0,
    "breadth_scale": 3.0,
    "max_velocity_bonus": 1.0,
    "velocity_scale": 5.0,
    "swedish_weight": 0.5,
    "score_version": "test",
    "half_life_days": 3,
    "default_source_weight": 1.0,
    "previous_days": 6,
    "authority_base_factor": 1.5,
    "authority_total_start_factor": 10.0,
    "authority_bonus_half_life_days": 0.7,
}
NOW = datetime(2026, 11, 5, 12, tzinfo=timezone.utc)


def rows():
    return {
        "topics": [{"id": 1}, {"id": 2}],
        "topic_articles": [
            {"topic_id": 1, "news_id": 101},
            {"topic_id": 2, "news_id": 102},
        ],
        "news": [
            {
                "id": 101,
                "title": "Title",
                "description": "Description",
                "source": " Breakit ",
                "source_normalized": "breakit",
                "published": "2026-11-05T10:00:00+00:00",
                "link": "https://example.test/101",
            },
            {
                "id": 102,
                "title": "Other",
                "description": "Description",
                "source": "Reuters",
                "source_normalized": "reuters",
                "published": "not-a-date",
                "link": "https://example.test/102",
            },
        ],
        "source_registry": [
            {"source_normalized": "breakit", "source_type": "media"},
            {"source_normalized": "reuters", "source_type": None},
        ],
    }


def paged_request(
    data, calls, *, fail_table=None, fail_offset=None, patch_response=None
):
    def fake_request(url, key, *, method="GET", payload=None):
        calls.append((method, url, payload))
        table = url.split("/rest/v1/")[1].split("?")[0]
        if method == "PATCH":
            return patch_response if patch_response is not None else [{"id": 1}]
        query = parse_qs(urlparse(url).query)
        offset = int(query["offset"][0])
        if table == fail_table and (fail_offset is None or offset == fail_offset):
            raise adapter.SupabaseReadError("later page failed")
        values = data[table]
        page = values[offset : offset + 1]
        return page

    return fake_request


def test_read_only_ranks_all_memberships_and_does_not_write(monkeypatch):
    calls = []
    monkeypatch.setattr(adapter, "request_json", paged_request(rows(), calls))

    result = adapter.run_ranking(
        url="https://example.test", key="secret", now=NOW, config=CONFIG
    )

    assert result["written"] is False
    assert [item["topic_id"] for item in result["topics"]] == [1, 2]
    assert (
        result["topics"][0]["values"]["score_breakdown"]["metrics"]["article_count"]
        == 1
    )
    assert result["skipped"] == {2: "no valid articles; ranking fields will be cleared"}
    assert all(method == "GET" for method, _, _ in calls)


def test_normalized_ranking_copy_merges_variants_without_mutating_input(monkeypatch):
    data = rows()
    data["topic_articles"] = [
        {"topic_id": 1, "news_id": 101},
        {"topic_id": 1, "news_id": 102},
    ]
    data["news"][1].update(
        {
            "published": "2026-11-05T09:00:00+00:00",
            "source": "BREAKIT",
            "source_normalized": "breakit",
        }
    )
    data["source_registry"][0]["source_type"] = "authority"
    original = deepcopy(data["news"])
    calls = []
    monkeypatch.setattr(adapter, "request_json", paged_request(data, calls))
    topics, warnings = adapter.read_input("https://example.test", "secret")

    assert warnings == []
    assert topics[0]["articles"][0]["source"] == "breakit"
    assert topics[0]["articles"][1]["source"] == "breakit"
    assert len({article["source"] for article in topics[0]["articles"]}) == 1
    ranked = adapter.rank_topics(
        topics[:1],
        NOW,
        CONFIG["source_weights"],
        CONFIG["swedish_sources"],
        max_breadth_bonus=CONFIG["max_breadth_bonus"],
        breadth_scale=CONFIG["breadth_scale"],
        max_velocity_bonus=CONFIG["max_velocity_bonus"],
        velocity_scale=CONFIG["velocity_scale"],
        swedish_weight=CONFIG["swedish_weight"],
        score_version=CONFIG["score_version"],
        half_life_days=CONFIG["half_life_days"],
        default_weight=CONFIG["default_source_weight"],
        previous_days=CONFIG["previous_days"],
    )
    assert ranked[0]["score_breakdown"]["metrics"]["source_count"] == 1
    assert data["news"] == original


def test_writes_only_four_fields_and_confirms_each_topic(monkeypatch):
    calls = []
    responses = iter([[{"id": 1}], [{"id": 2}]])

    def request(url, key, *, method="GET", payload=None):
        if method == "PATCH":
            calls.append((method, url, payload))
            return next(responses)
        return paged_request(rows(), calls)(url, key, method=method, payload=payload)

    monkeypatch.setattr(adapter, "request_json", request)
    result = adapter.run_ranking(
        url="https://example.test", key="secret", write=True, now=NOW, config=CONFIG
    )

    patches = [payload for method, _, payload in calls if method == "PATCH"]
    assert len(patches) == 2
    assert all(set(payload) == set(adapter.RANKING_FIELDS) for payload in patches)
    assert result["writes"] == {
        "requested": True,
        "confirmed": [1, 2],
        "failed": [],
    }


def test_wrong_update_confirmation_is_reported(monkeypatch):
    calls = []
    monkeypatch.setattr(
        adapter,
        "request_json",
        paged_request(rows(), calls, patch_response=[{"id": 1}]),
    )
    result = adapter.run_ranking(
        url="https://example.test", key="secret", write=True, now=NOW, config=CONFIG
    )

    assert result["writes"]["confirmed"] == [1]
    assert result["writes"]["failed"] == [2]
    assert "write failed" in result["errors"][2]


def test_first_write_failure_does_not_stop_next_confirmation(monkeypatch):
    calls = []
    responses = iter([[{"id": 999}], [{"id": 2}]])

    def request(url, key, *, method="GET", payload=None):
        if method == "PATCH":
            calls.append((method, url, payload))
            return next(responses)
        return paged_request(rows(), calls)(url, key, method=method, payload=payload)

    monkeypatch.setattr(adapter, "request_json", request)
    result = adapter.run_ranking(
        url="https://example.test", key="secret", write=True, now=NOW, config=CONFIG
    )

    assert result["writes"] == {
        "requested": True,
        "confirmed": [2],
        "failed": [1],
    }
    assert "write failed" in result["errors"][1]


def test_malformed_write_confirmation_is_an_isolated_failure(monkeypatch):
    calls = []
    responses = iter([[None], [{"id": 2}]])

    def request(url, key, *, method="GET", payload=None):
        if method == "PATCH":
            calls.append((method, url, payload))
            return next(responses)
        return paged_request(rows(), calls)(url, key, method=method, payload=payload)

    monkeypatch.setattr(adapter, "request_json", request)
    result = adapter.run_ranking(
        url="https://example.test", key="secret", write=True, now=NOW, config=CONFIG
    )

    assert result["writes"]["failed"] == [1]
    assert result["writes"]["confirmed"] == [2]
    assert "write failed" in result["errors"][1]


def test_calculation_error_does_not_block_next_topic_write(monkeypatch):
    calls = []
    original_rank_topics = adapter.rank_topics
    data = rows()
    data["news"][1]["published"] = "2026-11-05T09:00:00+00:00"
    request_reads = paged_request(data, calls)

    def fake_rank(topics, *args, **kwargs):
        if topics[0]["id"] == 1:
            raise RuntimeError("unexpected")
        return original_rank_topics(topics, *args, **kwargs)

    def request(url, key, *, method="GET", payload=None):
        if method == "PATCH":
            calls.append((method, url, payload))
            return [{"id": 2}]
        return request_reads(url, key, method=method, payload=payload)

    monkeypatch.setattr(adapter, "request_json", request)
    monkeypatch.setattr(adapter, "rank_topics", fake_rank)
    result = adapter.run_ranking(
        url="https://example.test", key="secret", write=True, now=NOW, config=CONFIG
    )

    assert result["writes"]["confirmed"] == [2]
    assert result["writes"]["failed"] == []
    assert result["topics"][0]["topic_id"] == 2
    assert "calculation failed" in result["errors"][1]


def test_missing_article_aborts_before_writing(monkeypatch):
    data = rows()
    data["topic_articles"].append({"topic_id": 1, "news_id": 999})
    calls = []
    monkeypatch.setattr(adapter, "request_json", paged_request(data, calls))

    with pytest.raises(adapter.SupabaseReadError):
        adapter.run_ranking(
            url="https://example.test", key="secret", write=True, now=NOW, config=CONFIG
        )
    assert not any(method == "PATCH" for method, _, _ in calls)


def test_later_page_read_error_aborts_before_writing(monkeypatch):
    calls = []
    monkeypatch.setattr(
        adapter,
        "request_json",
        paged_request(rows(), calls, fail_table="news", fail_offset=1),
    )

    with pytest.raises(adapter.SupabaseReadError):
        adapter.run_ranking(
            url="https://example.test", key="secret", write=True, now=NOW, config=CONFIG
        )
    assert not any(method == "PATCH" for method, _, _ in calls)


def test_null_payload_is_exactly_four_null_fields(monkeypatch):
    data = rows()
    data["topic_articles"] = []
    calls = []
    monkeypatch.setattr(adapter, "request_json", paged_request(data, calls))

    result = adapter.run_ranking(
        url="https://example.test", key="secret", write=True, now=NOW, config=CONFIG
    )

    patches = [payload for method, _, payload in calls if method == "PATCH"]
    assert patches == [
        {field: None for field in adapter.RANKING_FIELDS},
        {field: None for field in adapter.RANKING_FIELDS},
    ]
    assert result["skipped"] == {
        1: "no valid articles; ranking fields will be cleared",
        2: "no valid articles; ranking fields will be cleared",
    }


def test_unexpected_calculation_error_is_not_cleared(monkeypatch):
    calls = []
    monkeypatch.setattr(adapter, "request_json", paged_request(rows(), calls))
    monkeypatch.setattr(
        adapter,
        "rank_topics",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("unexpected")),
    )

    result = adapter.run_ranking(
        url="https://example.test", key="secret", write=True, now=NOW, config=CONFIG
    )

    assert result["topics"] == []
    assert result["writes"]["confirmed"] == []
    assert "calculation failed" in result["errors"][1]
    assert not any(method == "PATCH" for method, _, _ in calls)


def test_missing_stored_normalization_is_a_warning(monkeypatch):
    data = rows()
    data["news"][0]["source_normalized"] = None
    calls = []
    monkeypatch.setattr(adapter, "request_json", paged_request(data, calls))

    result = adapter.run_ranking(
        url="https://example.test", key="secret", now=NOW, config=CONFIG
    )

    assert result["warnings"] == ["news_id=101 has no stored source normalization."]
    metrics = result["topics"][0]["values"]["score_breakdown"]["metrics"]
    assert metrics["source_count"] == 1
    assert metrics["swedish_signal"] == 1.0


def test_mismatched_stored_normalization_aborts_before_writing(monkeypatch):
    data = rows()
    data["news"][0]["source_normalized"] = "wrong"
    calls = []
    monkeypatch.setattr(adapter, "request_json", paged_request(data, calls))

    with pytest.raises(adapter.SupabaseReadError, match="normalization"):
        adapter.run_ranking(
            url="https://example.test", key="secret", write=True, now=NOW, config=CONFIG
        )
    assert not any(method == "PATCH" for method, _, _ in calls)


def test_missing_registry_match_is_rankable_without_bonus(monkeypatch):
    data = rows()
    data["source_registry"] = []
    calls = []
    monkeypatch.setattr(adapter, "request_json", paged_request(data, calls))

    result = adapter.run_ranking(
        url="https://example.test", key="secret", now=NOW, config=CONFIG
    )

    assert result["errors"] == {}
    assert (
        result["topics"][0]["values"]["score_breakdown"]["metrics"][
            "authority_article_score"
        ]
        == 0
    )


def test_registry_authority_classification_affects_run_ranking_contributions(monkeypatch):
    data = rows()
    data["source_registry"][0]["source_type"] = "authority"
    data["news"][0]["published"] = NOW.isoformat()
    calls = []
    monkeypatch.setattr(adapter, "request_json", paged_request(data, calls))
    config = {
        **CONFIG,
        "authority_base_factor": 2.0,
        "authority_total_start_factor": 6.5,
        "authority_bonus_half_life_days": 1.3,
    }

    result = adapter.run_ranking(
        url="https://example.test", key="secret", now=NOW, config=config
    )

    metrics = result["topics"][0]["values"]["score_breakdown"]["metrics"]
    assert metrics["authority_base_score"] == pytest.approx(2.0)
    assert metrics["authority_bonus_score"] == pytest.approx(4.5)
    assert metrics["authority_article_score"] == pytest.approx(6.5)


def test_registry_read_error_is_not_treated_as_unclassified(monkeypatch):
    calls = []
    monkeypatch.setattr(
        adapter,
        "request_json",
        paged_request(rows(), calls, fail_table="source_registry"),
    )

    with pytest.raises(adapter.SupabaseReadError):
        adapter.run_ranking(
            url="https://example.test", key="secret", now=NOW, config=CONFIG
        )
