from copy import deepcopy
from datetime import datetime, timezone

import pytest

from rank_topics import rank_topics


@pytest.fixture
def options():
    return {
        "now": datetime(2026, 11, 1, 12, tzinfo=timezone.utc),
        "source_weights": {"IMY": 3.0},
        "swedish_sources": {"IMY"},
        "max_breadth_bonus": 0.5,
        "max_velocity_bonus": 0.25,
        "swedish_weight": 1.0,
        "score_version": "test-v1",
    }


@pytest.fixture
def topics():
    return [
        {"id": 30, "articles": [article(1, "Other")]},
        {"id": 20, "articles": [article(2, "IMY")]},
        {"id": 10, "articles": [article(3, "Other")]},
        {"id": 40, "articles": []},
    ]


def article(news_id, source):
    return {"id": news_id, "source": source, "published": "2026-11-01T12:00:00Z"}


def test_orders_by_score_then_topic_id(topics, options):
    result = rank_topics(topics, **options)
    assert [item["id"] for item in result] == [20, 10, 30]
    assert [item["score"] for item in result] == pytest.approx(
        [6.5, 1.1666666666666667, 1.1666666666666667]
    )
    assert all(
        (item["score_calculated_at"] == "2026-11-01T12:00:00+00:00" for item in result)
    )
    assert all((item["score_version"] == "test-v1" for item in result))
    assert [
        item["score_breakdown"]["metrics"]["contributions"][0]["news_id"]
        for item in result
    ] == [2, 3, 1]


@pytest.mark.parametrize(
    ("top_n", "expected_ids"),
    [(None, [20, 10, 30]), (1, [20]), (2, [20, 10]), (20, [20, 10, 30])],
)
def test_applies_limit_after_sorting_and_excluding_empty_topics(
    top_n, expected_ids, topics, options
):
    topics.insert(0, {"id": 5, "articles": []})
    result = rank_topics(topics, top_n=top_n, **options)
    assert [item["id"] for item in result] == expected_ids


@pytest.mark.parametrize("topics", [[], [{"id": 1, "articles": []}]])
def test_returns_empty_list_without_articles(topics, options):
    assert rank_topics(topics, **options) == []


@pytest.mark.parametrize("top_n", [0, -1, 1.5, "2", True, False])
def test_rejects_invalid_limit(top_n, topics, options):
    with pytest.raises(ValueError, match="top_n"):
        rank_topics(topics, top_n=top_n, **options)


@pytest.mark.parametrize("topic_id", [True, False, "1", 1.5, None])
def test_rejects_non_integer_topic_id(topic_id, options):
    with pytest.raises(ValueError, match="topic id must be an integer"):
        rank_topics([{"id": topic_id, "articles": []}], **options)


def test_rejects_duplicate_topic_ids_even_when_topic_is_empty(options):
    topics = [{"id": 1, "articles": []}, {"id": 1, "articles": [article(1, "IMY")]}]
    with pytest.raises(ValueError, match="topic ids must be unique"):
        rank_topics(topics, **options)


def test_is_repeatable_without_changing_input(topics, options):
    original_topics = deepcopy(topics)
    original_options = deepcopy(options)
    first = rank_topics(topics, **options)
    second = rank_topics(topics, **options)
    reversed_result = rank_topics(list(reversed(topics)), **options)
    assert first == second == reversed_result
    assert topics == original_topics
    assert options == original_options


def test_accepts_generators_for_topics_articles_and_swedish_sources(topics, options):
    expected = rank_topics(topics, **options)
    options["swedish_sources"] = iter(options["swedish_sources"])
    generated_topics = (
        {"id": topic["id"], "articles": iter(topic["articles"])} for topic in topics
    )
    assert rank_topics(generated_topics, **options) == expected


def test_same_article_can_contribute_to_different_topics(options):
    shared_article = article(1, "IMY")
    topics = [
        {"id": 2, "articles": [shared_article]},
        {"id": 1, "articles": [shared_article]},
    ]
    result = rank_topics(topics, **options)
    assert [item["id"] for item in result] == [1, 2]
    assert [item["score"] for item in result] == pytest.approx([6.5, 6.5])


def test_passes_custom_calculation_settings(options):
    topics = [
        {
            "id": 1,
            "articles": [
                {"id": 1, "source": "Unknown", "published": "2026-10-26T12:00:00Z"}
            ],
        }
    ]
    options.update(
        max_breadth_bonus=0.0,
        max_velocity_bonus=0.0,
        swedish_weight=0.0,
        half_life_days=6,
        default_weight=2.0,
        previous_days=2,
        score_version="test-custom",
    )
    result = rank_topics(topics, **options)[0]
    assert result["score"] == pytest.approx(1.0)
    assert result["score_version"] == "test-custom"
    config = result["score_breakdown"]["config"]
    assert config["half_life_days"] == 6
    assert config["default_source_weight"] == 2.0
    assert config["previous_days"] == 2


def test_skips_invalid_articles_and_continues_ranking(options, caplog):
    invalid_article = {"id": 99, "source": "IMY", "published": "2026-11-01T13:00:00Z"}
    topics = [
        {"id": 10, "articles": [invalid_article, article(1, "Other")]},
        {"id": 20, "articles": [invalid_article]},
        {"id": 30, "articles": [article(2, "IMY")]},
    ]
    original_topics = deepcopy(topics)
    result = rank_topics(topics, **options)
    assert [item["id"] for item in result] == [30, 10]
    metrics = result[1]["score_breakdown"]["metrics"]
    assert metrics["article_count"] == 1
    assert metrics["source_count"] == 1
    assert metrics["recent_count"] == 1
    assert metrics["swedish_signal"] == 0.0
    assert metrics["swedish_article_score"] == pytest.approx(0.0)
    assert [item["news_id"] for item in metrics["contributions"]] == [1]
    assert "Skipping article news_id=99 in topic_id=10" in caplog.text
    assert "Skipping topic_id=20: no valid articles" in caplog.text
    assert topics == original_topics
