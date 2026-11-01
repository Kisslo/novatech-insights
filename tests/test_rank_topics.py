from copy import deepcopy
from datetime import datetime, timezone

import pytest

from rank_topics import (
    build_topic_score_result,
    calculate_article_contribution,
    calculate_swedish_signal,
    calculate_time_decay,
    calculate_topic_article_score,
    calculate_topic_metrics,
    calculate_topic_ranking,
    calculate_topic_score,
    calculate_topic_velocity,
    calculate_velocity,
    count_distinct_sources,
    count_velocity_articles,
    get_source_weight,
    parse_publication_time,
)


def test_count_distinct_sources_counts_each_source_once():
    articles = [
        {"news_id": 1, "source": "TechCrunch"},
        {"news_id": 2, "source": "Reuters"},
        {"news_id": 3, "source": "TechCrunch"},
    ]

    result = count_distinct_sources(articles)

    assert result == 2


def test_count_distinct_sources_returns_zero_for_empty_list():
    assert count_distinct_sources([]) == 0


def test_count_distinct_sources_returns_zero_when_all_sources_are_missing():
    articles = [
        {"news_id": 1, "source": None},
        {"news_id": 2, "source": ""},
        {"news_id": 3},
    ]

    assert count_distinct_sources(articles) == 0


def test_count_distinct_sources_ignores_missing_sources():
    articles = [
        {"news_id": 1, "source": "Reuters"},
        {"news_id": 2, "source": None},
        {"news_id": 3, "source": ""},
        {"news_id": 4},
    ]

    assert count_distinct_sources(articles) == 1


def test_time_decay_halves_weight_after_three_days():
    result = calculate_time_decay(age_days=3, half_life_days=3)

    assert result == 0.5


def test_time_decay_before_half_life():
    result = calculate_time_decay(age_days=1.5, half_life_days=3)

    assert result == pytest.approx(0.70710678)


def test_time_decay_returns_full_weight_for_new_article():
    result = calculate_time_decay(age_days=0, half_life_days=3)

    assert result == 1.0


def test_time_decay_uses_configured_half_life():
    result = calculate_time_decay(age_days=7, half_life_days=7)

    assert result == 0.5


@pytest.mark.parametrize("half_life_days", [0, -3])
def test_time_decay_rejects_non_positive_half_life(half_life_days):
    with pytest.raises(ValueError):
        calculate_time_decay(age_days=1, half_life_days=half_life_days)


def test_time_decay_rejects_negative_age():
    with pytest.raises(ValueError):
        calculate_time_decay(age_days=-1, half_life_days=3)


@pytest.mark.parametrize(
    ("recent_count", "previous_count", "previous_days", "expected"),
    [
        (6, 14, 7, 3.0),
        (2, 14, 7, 1.0),
        (0, 14, 7, 0.0),
        (3, 0, 7, 3.0),
        (3, 2, 7, 3.0),
        (6, 12, 3, 1.5),
    ],
)
def test_calculate_velocity(recent_count, previous_count, previous_days, expected):
    result = calculate_velocity(recent_count, previous_count, previous_days)

    assert result == pytest.approx(expected)


def test_calculate_velocity_defaults_to_seven_days():
    assert calculate_velocity(6, 14) == pytest.approx(3.0)


@pytest.mark.parametrize(
    ("recent_count", "previous_count"),
    [(-1, 14), (3, -1)],
)
def test_calculate_velocity_rejects_negative_counts(recent_count, previous_count):
    with pytest.raises(ValueError, match="article counts must not be negative"):
        calculate_velocity(recent_count, previous_count)


@pytest.mark.parametrize("previous_days", [0, -7])
def test_calculate_velocity_rejects_invalid_previous_days(previous_days):
    with pytest.raises(ValueError, match="previous_days must be greater than zero"):
        calculate_velocity(3, 14, previous_days)


@pytest.mark.parametrize(
    "value",
    [
        "2026-10-30T12:00:00Z",
        "2026-10-30T12:00:00+00:00",
        "2026-10-30T13:00:00+01:00",
        " 2026-10-30T12:00:00Z ",
    ],
)
def test_parse_publication_time_converts_to_utc(value):
    result = parse_publication_time(value)

    assert result == datetime(2026, 10, 30, 12, tzinfo=timezone.utc)
    assert result.tzinfo is timezone.utc


@pytest.mark.parametrize("value", [None, "", "   ", 123])
def test_parse_publication_time_rejects_missing_or_non_string_values(value):
    with pytest.raises(ValueError, match="non-empty ISO timestamp"):
        parse_publication_time(value)


@pytest.mark.parametrize(
    "value",
    [
        "2026-10-30T12:00:00",
        "2026-10-30",
    ],
)
def test_parse_publication_time_rejects_missing_timezone(value):
    with pytest.raises(ValueError, match="must include a timezone"):
        parse_publication_time(value)


@pytest.mark.parametrize(
    "value",
    [
        "not-a-date",
        "2026-13-30T12:00:00Z",
    ],
)
def test_parse_publication_time_rejects_invalid_dates(value):
    with pytest.raises(ValueError):
        parse_publication_time(value)


@pytest.mark.parametrize(
    ("published", "expected"),
    [
        ("2026-11-01T11:00:00Z", (1, 0)),
        ("2026-11-01T12:00:00Z", (1, 0)),
        ("2026-10-31T12:00:00Z", (0, 1)),
        ("2026-10-28T12:00:00Z", (0, 1)),
        ("2026-10-24T12:00:00Z", (0, 0)),
        ("2026-10-23T12:00:00Z", (0, 0)),
        ("2026-11-01T13:00:00Z", (0, 0)),
    ],
)
def test_count_velocity_articles_time_windows(published, expected):
    now = datetime(2026, 11, 1, 12, tzinfo=timezone.utc)
    articles = [{"id": 1, "published": published}]

    assert count_velocity_articles(articles, now) == expected


def test_count_velocity_articles_counts_each_id_once():
    now = datetime(2026, 11, 1, 12, tzinfo=timezone.utc)
    articles = [
        {"id": 1, "published": "2026-11-01T11:00:00Z"},
        {"id": 1, "published": "2026-11-01T11:00:00Z"},
        {"id": 2, "published": "2026-10-30T12:00:00Z"},
        {"id": 2, "published": "2026-10-30T12:00:00Z"},
    ]

    assert count_velocity_articles(articles, now) == (1, 1)


def test_count_velocity_articles_empty_input():
    now = datetime(2026, 11, 1, 12, tzinfo=timezone.utc)

    assert count_velocity_articles([], now) == (0, 0)


def test_count_velocity_articles_configurable_previous_days():
    now = datetime(2026, 11, 1, 12, tzinfo=timezone.utc)
    articles = [
        {"id": 1, "published": "2026-10-29T12:00:00Z"},
        {"id": 2, "published": "2026-10-28T12:00:00Z"},
    ]

    assert count_velocity_articles(articles, now, previous_days=3) == (0, 1)


def test_count_velocity_articles_handles_timezone_offset():
    now = datetime(2026, 11, 1, 12, tzinfo=timezone.utc)
    articles = [{"id": 1, "published": "2026-11-01T12:00:00+01:00"}]

    assert count_velocity_articles(articles, now) == (1, 0)


def test_count_velocity_articles_rejects_now_without_timezone():
    now = datetime(2026, 11, 1, 12)

    with pytest.raises(ValueError, match="now must include a timezone"):
        count_velocity_articles([], now)


@pytest.mark.parametrize("previous_days", [0, -7])
def test_count_velocity_articles_rejects_invalid_previous_days(previous_days):
    now = datetime(2026, 11, 1, 12, tzinfo=timezone.utc)

    with pytest.raises(ValueError, match="previous_days must be greater than zero"):
        count_velocity_articles([], now, previous_days)


def test_count_velocity_articles_rejects_missing_id():
    now = datetime(2026, 11, 1, 12, tzinfo=timezone.utc)
    articles = [{"published": "2026-11-01T11:00:00Z"}]

    with pytest.raises(KeyError, match="id"):
        count_velocity_articles(articles, now)


@pytest.mark.parametrize("published", [None, "not-a-date"])
def test_count_velocity_articles_rejects_invalid_publication_time(published):
    now = datetime(2026, 11, 1, 12, tzinfo=timezone.utc)
    articles = [{"id": 1, "published": published}]

    with pytest.raises(ValueError):
        count_velocity_articles(articles, now)


def test_calculate_topic_velocity_returns_score_and_counts():
    now = datetime(2026, 11, 1, 12, tzinfo=timezone.utc)
    articles = [{"id": i, "published": "2026-11-01T11:00:00Z"} for i in range(1, 7)] + [
        {"id": i, "published": "2026-10-28T12:00:00Z"} for i in range(7, 21)
    ]

    result = calculate_topic_velocity(articles, now)

    assert result["velocity"] == pytest.approx(3.0)
    assert result["recent_count"] == 6
    assert result["previous_count"] == 14
    assert result["previous_days"] == 7


def test_calculate_topic_velocity_without_history():
    now = datetime(2026, 11, 1, 12, tzinfo=timezone.utc)
    articles = [
        {"id": 1, "published": "2026-11-01T11:00:00Z"},
        {"id": 2, "published": "2026-11-01T10:00:00Z"},
    ]

    result = calculate_topic_velocity(articles, now)

    assert result["velocity"] == pytest.approx(2.0)
    assert result["recent_count"] == 2
    assert result["previous_count"] == 0


def test_calculate_topic_velocity_empty_input():
    now = datetime(2026, 11, 1, 12, tzinfo=timezone.utc)

    result = calculate_topic_velocity([], now)

    assert result == {
        "velocity": 0.0,
        "recent_count": 0,
        "previous_count": 0,
        "previous_days": 7,
    }


def test_calculate_topic_velocity_uses_configured_previous_days():
    now = datetime(2026, 11, 1, 12, tzinfo=timezone.utc)
    articles = [
        {"id": 1, "published": "2026-11-01T11:00:00Z"},
        {"id": 2, "published": "2026-10-30T13:00:00Z"},
        {"id": 3, "published": "2026-10-30T13:00:00Z"},
    ]

    result = calculate_topic_velocity(articles, now, previous_days=1)

    assert result["velocity"] == pytest.approx(0.5)
    assert result["recent_count"] == 1
    assert result["previous_count"] == 2
    assert result["previous_days"] == 1


@pytest.mark.parametrize(
    ("articles", "swedish_sources", "expected"),
    [
        (
            [{"source": "TechCrunch"}, {"source": "Breakit"}],
            ["Breakit", "Computer Sweden"],
            1.0,
        ),
        (
            [{"source": "TechCrunch"}],
            ["Breakit", "Computer Sweden"],
            0.0,
        ),
        (
            [{"source": "Breakit"}, {"source": "Breakit"}],
            ["Breakit"],
            1.0,
        ),
        (
            [{"source": " BREAKIT "}],
            [" breakit "],
            1.0,
        ),
        (
            [],
            ["Breakit"],
            0.0,
        ),
        (
            [{"source": "Breakit"}],
            [],
            0.0,
        ),
        (
            [{}, {"source": None}, {"source": ""}, {"source": "   "}],
            ["Breakit"],
            0.0,
        ),
        (
            [{"source": "Breakit"}],
            [None, "", "   ", "Breakit"],
            1.0,
        ),
        (
            [{"source": "Breakit Opinion"}],
            ["Breakit"],
            0.0,
        ),
    ],
)
def test_calculate_swedish_signal(articles, swedish_sources, expected):
    assert calculate_swedish_signal(articles, swedish_sources) == expected


@pytest.mark.parametrize(
    ("source", "source_weights", "default_weight", "expected"),
    [
        ("IMY", {"IMY": 3.0}, 1.0, 3.0),
        ("TechCrunch", {"IMY": 3.0}, 1.0, 1.0),
        ("TechCrunch", {}, 0.5, 0.5),
        (" IMY ", {" imy ": 3.0}, 1.0, 3.0),
        ("IMY", {"IMY": 0.0}, 1.0, 0.0),
        (None, {"IMY": 3.0}, 1.0, 1.0),
        ("", {"IMY": 3.0}, 1.0, 1.0),
        ("   ", {"IMY": 3.0}, 1.0, 1.0),
        ("IMY Opinion", {"IMY": 3.0}, 1.0, 1.0),
    ],
)
def test_get_source_weight(source, source_weights, default_weight, expected):
    result = get_source_weight(source, source_weights, default_weight)

    assert result == pytest.approx(expected)


def test_get_source_weight_defaults_to_one():
    assert get_source_weight("Unknown", {}) == pytest.approx(1.0)


def test_get_source_weight_rejects_negative_default():
    with pytest.raises(ValueError, match="default_weight must not be negative"):
        get_source_weight("IMY", {"IMY": 3.0}, default_weight=-1.0)


def test_get_source_weight_rejects_negative_configured_weight():
    with pytest.raises(ValueError, match="source weights must not be negative"):
        get_source_weight("IMY", {"IMY": -1.0})


def test_get_source_weight_validates_unmatched_weights():
    with pytest.raises(ValueError, match="source weights must not be negative"):
        get_source_weight("TechCrunch", {"IMY": -1.0})


@pytest.mark.parametrize(
    ("published", "expected_time_weight", "expected_contribution"),
    [
        ("2026-11-01T12:00:00Z", 1.0, 3.0),
        ("2026-10-29T12:00:00Z", 0.5, 1.5),
        ("2026-10-26T12:00:00Z", 0.25, 0.75),
        ("2026-10-31T00:00:00Z", 0.5**0.5, 3.0 * 0.5**0.5),
    ],
)
def test_calculate_article_contribution_applies_time_decay(
    published, expected_time_weight, expected_contribution
):
    now = datetime(2026, 11, 1, 12, tzinfo=timezone.utc)
    article = {"source": "IMY", "published": published}

    result = calculate_article_contribution(article, now, {"IMY": 3.0})

    assert result["source_weight"] == pytest.approx(3.0)
    assert result["time_weight"] == pytest.approx(expected_time_weight)
    assert result["contribution"] == pytest.approx(expected_contribution)


def test_calculate_article_contribution_uses_default_source_weight():
    now = datetime(2026, 11, 1, 12, tzinfo=timezone.utc)
    article = {
        "source": "Unknown",
        "published": "2026-10-29T12:00:00Z",
    }

    result = calculate_article_contribution(article, now, {}, default_weight=2.0)

    assert result["source_weight"] == pytest.approx(2.0)
    assert result["time_weight"] == pytest.approx(0.5)
    assert result["contribution"] == pytest.approx(1.0)


def test_calculate_article_contribution_uses_configured_half_life():
    now = datetime(2026, 11, 1, 12, tzinfo=timezone.utc)
    article = {
        "source": "IMY",
        "published": "2026-10-26T12:00:00Z",
    }

    result = calculate_article_contribution(
        article, now, {"IMY": 3.0}, half_life_days=6
    )

    assert result["time_weight"] == pytest.approx(0.5)
    assert result["contribution"] == pytest.approx(1.5)


def test_calculate_article_contribution_rejects_future_publication():
    now = datetime(2026, 11, 1, 12, tzinfo=timezone.utc)
    article = {
        "source": "IMY",
        "published": "2026-11-01T13:00:00Z",
    }

    with pytest.raises(ValueError, match="age_days must not be negative"):
        calculate_article_contribution(article, now, {})


def test_calculate_article_contribution_rejects_now_without_timezone():
    now = datetime(2026, 11, 1, 12)
    article = {
        "source": "IMY",
        "published": "2026-11-01T11:00:00Z",
    }

    with pytest.raises(ValueError, match="now must include a timezone"):
        calculate_article_contribution(article, now, {})


def test_calculate_topic_article_score_sums_contributions():
    now = datetime(2026, 11, 1, 12, tzinfo=timezone.utc)
    articles = [
        {
            "id": 1,
            "source": "IMY",
            "published": "2026-11-01T12:00:00Z",
        },
        {
            "id": 2,
            "source": "Other",
            "published": "2026-10-29T12:00:00Z",
        },
    ]

    result = calculate_topic_article_score(articles, now, {"IMY": 3.0})

    assert result["article_score"] == pytest.approx(3.5)
    assert result["article_count"] == 2
    assert [item["news_id"] for item in result["contributions"]] == [1, 2]
    assert result["contributions"][0]["contribution"] == pytest.approx(3.0)
    assert result["contributions"][1]["contribution"] == pytest.approx(0.5)


def test_calculate_topic_article_score_counts_each_id_once():
    now = datetime(2026, 11, 1, 12, tzinfo=timezone.utc)
    article = {
        "id": 1,
        "source": "IMY",
        "published": "2026-11-01T12:00:00Z",
    }

    result = calculate_topic_article_score([article, dict(article)], now, {"IMY": 3.0})

    assert result["article_score"] == pytest.approx(3.0)
    assert result["article_count"] == 1
    assert len(result["contributions"]) == 1


def test_calculate_topic_article_score_keeps_distinct_articles_from_same_source():
    now = datetime(2026, 11, 1, 12, tzinfo=timezone.utc)
    articles = [
        {
            "id": article_id,
            "source": "IMY",
            "published": "2026-11-01T12:00:00Z",
        }
        for article_id in (1, 2)
    ]

    result = calculate_topic_article_score(articles, now, {"IMY": 3.0})

    assert result["article_score"] == pytest.approx(6.0)
    assert result["article_count"] == 2


def test_calculate_topic_article_score_empty_input():
    now = datetime(2026, 11, 1, 12, tzinfo=timezone.utc)

    result = calculate_topic_article_score([], now, {})

    assert result == {
        "article_score": 0,
        "article_count": 0,
        "contributions": [],
    }


def test_calculate_topic_article_score_passes_configuration():
    now = datetime(2026, 11, 1, 12, tzinfo=timezone.utc)
    articles = [
        {
            "id": 1,
            "source": "Unknown",
            "published": "2026-10-26T12:00:00Z",
        }
    ]

    result = calculate_topic_article_score(
        articles,
        now,
        {},
        half_life_days=6,
        default_weight=2.0,
    )

    assert result["article_score"] == pytest.approx(1.0)
    assert result["contributions"][0]["source_weight"] == pytest.approx(2.0)
    assert result["contributions"][0]["time_weight"] == pytest.approx(0.5)


def test_calculate_topic_article_score_rejects_missing_id():
    now = datetime(2026, 11, 1, 12, tzinfo=timezone.utc)
    articles = [{"source": "IMY", "published": "2026-11-01T12:00:00Z"}]

    with pytest.raises(KeyError, match="id"):
        calculate_topic_article_score(articles, now, {})


def test_calculate_topic_metrics_combines_components():
    now = datetime(2026, 11, 1, 12, tzinfo=timezone.utc)
    articles = [
        {
            "id": 1,
            "source": "IMY",
            "published": "2026-11-01T12:00:00Z",
        },
        {
            "id": 2,
            "source": "Other",
            "published": "2026-10-29T12:00:00Z",
        },
    ]

    result = calculate_topic_metrics(
        articles,
        now,
        source_weights={"IMY": 3.0},
        swedish_sources={"IMY"},
    )

    assert result["article_score"] == pytest.approx(3.5)
    assert result["article_count"] == 2
    assert result["source_count"] == 2
    assert result["swedish_signal"] == pytest.approx(1.0)
    assert result["velocity"] == pytest.approx(1.0)
    assert result["recent_count"] == 1
    assert result["previous_count"] == 1
    assert result["previous_days"] == 7
    assert [item["news_id"] for item in result["contributions"]] == [1, 2]


def test_calculate_topic_metrics_passes_configuration():
    now = datetime(2026, 11, 1, 12, tzinfo=timezone.utc)
    articles = [
        {
            "id": 1,
            "source": "Unknown",
            "published": "2026-10-26T12:00:00Z",
        }
    ]

    result = calculate_topic_metrics(
        articles,
        now,
        source_weights={},
        swedish_sources=set(),
        half_life_days=6,
        default_weight=2.0,
        previous_days=2,
    )

    assert result["article_score"] == pytest.approx(1.0)
    assert result["contributions"][0]["time_weight"] == pytest.approx(0.5)
    assert result["contributions"][0]["source_weight"] == pytest.approx(2.0)
    assert result["previous_days"] == 2
    assert result["previous_count"] == 0
    assert result["swedish_signal"] == pytest.approx(0.0)


def test_calculate_topic_metrics_accepts_generator():
    now = datetime(2026, 11, 1, 12, tzinfo=timezone.utc)
    articles = (
        {
            "id": article_id,
            "source": "IMY",
            "published": "2026-11-01T12:00:00Z",
        }
        for article_id in (1, 2)
    )

    result = calculate_topic_metrics(
        articles,
        now,
        source_weights={"IMY": 3.0},
        swedish_sources={"IMY"},
    )

    assert result["article_score"] == pytest.approx(6.0)
    assert result["article_count"] == 2
    assert result["recent_count"] == 2
    assert result["source_count"] == 1
    assert result["swedish_signal"] == pytest.approx(1.0)


def test_calculate_topic_score_combines_weighted_signals():
    metrics = {
        "article_score": 4.0,
        "source_count": 2,
        "velocity": 3.0,
        "swedish_signal": 1.0,
    }

    result = calculate_topic_score(
        metrics,
        breadth_weight=0.5,
        velocity_weight=0.25,
        swedish_weight=1.0,
    )

    assert result == pytest.approx(15.0)


def test_calculate_topic_score_zero_weights_preserve_article_score():
    metrics = {
        "article_score": 4.0,
        "source_count": 2,
        "velocity": 3.0,
        "swedish_signal": 1.0,
    }

    result = calculate_topic_score(
        metrics,
        breadth_weight=0.0,
        velocity_weight=0.0,
        swedish_weight=0.0,
    )

    assert result == pytest.approx(4.0)


def test_calculate_topic_score_zero_article_score_gives_zero():
    metrics = {
        "article_score": 0.0,
        "source_count": 2,
        "velocity": 3.0,
        "swedish_signal": 1.0,
    }

    result = calculate_topic_score(
        metrics,
        breadth_weight=0.5,
        velocity_weight=0.25,
        swedish_weight=1.0,
    )

    assert result == pytest.approx(0.0)


@pytest.mark.parametrize(
    "breadth_weight, velocity_weight, swedish_weight",
    [
        (-0.1, 0.0, 0.0),
        (0.0, -0.1, 0.0),
        (0.0, 0.0, -0.1),
    ],
)
def test_calculate_topic_score_rejects_negative_weights(
    breadth_weight,
    velocity_weight,
    swedish_weight,
):
    metrics = {
        "article_score": 4.0,
        "source_count": 2,
        "velocity": 3.0,
        "swedish_signal": 1.0,
    }

    with pytest.raises(ValueError, match="ranking weights"):
        calculate_topic_score(
            metrics,
            breadth_weight=breadth_weight,
            velocity_weight=velocity_weight,
            swedish_weight=swedish_weight,
        )


def test_build_topic_score_result_contains_storage_fields():
    now = datetime(2026, 11, 1, 12, tzinfo=timezone.utc)
    metrics = {
        "article_score": 4.0,
        "source_count": 2,
        "velocity": 3.0,
        "swedish_signal": 1.0,
    }

    result = build_topic_score_result(
        metrics,
        now,
        breadth_weight=0.5,
        velocity_weight=0.25,
        swedish_weight=1.0,
        score_version="test-v1",
    )

    assert result["score"] == pytest.approx(15.0)
    assert result["score_calculated_at"] == "2026-11-01T12:00:00+00:00"
    assert result["score_version"] == "test-v1"

    breakdown = result["score_breakdown"]
    assert breakdown["metrics"] == metrics
    assert breakdown["weights"] == {
        "breadth": 0.5,
        "velocity": 0.25,
        "swedish": 1.0,
    }
    assert breakdown["contributions"] == pytest.approx(
        {
            "base": 4.0,
            "breadth": 4.0,
            "velocity": 3.0,
            "swedish": 4.0,
        }
    )
    assert sum(breakdown["contributions"].values()) == pytest.approx(result["score"])


def test_build_topic_score_result_rejects_naive_time():
    metrics = {
        "article_score": 4.0,
        "source_count": 2,
        "velocity": 3.0,
        "swedish_signal": 1.0,
    }

    with pytest.raises(ValueError, match="now must include a timezone"):
        build_topic_score_result(
            metrics,
            datetime(2026, 11, 1, 12),
            breadth_weight=0.5,
            velocity_weight=0.25,
            swedish_weight=1.0,
            score_version="test-v1",
        )


@pytest.mark.parametrize("score_version", ["", "   ", None, 1])
def test_build_topic_score_result_rejects_invalid_version(score_version):
    now = datetime(2026, 11, 1, 12, tzinfo=timezone.utc)
    metrics = {
        "article_score": 4.0,
        "source_count": 2,
        "velocity": 3.0,
        "swedish_signal": 1.0,
    }

    with pytest.raises(ValueError, match="score_version"):
        build_topic_score_result(
            metrics,
            now,
            breadth_weight=0.5,
            velocity_weight=0.25,
            swedish_weight=1.0,
            score_version=score_version,
        )


def test_calculate_topic_ranking_combines_full_pipeline():
    now = datetime(2026, 11, 1, 12, tzinfo=timezone.utc)
    articles = [
        {
            "id": 1,
            "source": "IMY",
            "published": "2026-11-01T12:00:00Z",
        },
        {
            "id": 2,
            "source": "Other",
            "published": "2026-10-29T12:00:00Z",
        },
    ]

    result = calculate_topic_ranking(
        articles,
        now,
        source_weights={"IMY": 3.0},
        swedish_sources={"IMY"},
        breadth_weight=0.5,
        velocity_weight=0.25,
        swedish_weight=1.0,
        score_version="test-v1",
    )

    assert result["score"] == pytest.approx(11.375)
    assert result["score_calculated_at"] == "2026-11-01T12:00:00+00:00"
    assert result["score_version"] == "test-v1"

    metrics = result["score_breakdown"]["metrics"]
    assert metrics["article_score"] == pytest.approx(3.5)
    assert metrics["article_count"] == 2
    assert metrics["source_count"] == 2
    assert metrics["velocity"] == pytest.approx(1.0)
    assert metrics["swedish_signal"] == pytest.approx(1.0)


def test_calculate_topic_ranking_passes_configuration():
    now = datetime(2026, 11, 1, 12, tzinfo=timezone.utc)
    articles = [
        {
            "id": 1,
            "source": "Unknown",
            "published": "2026-10-26T12:00:00Z",
        }
    ]

    result = calculate_topic_ranking(
        articles,
        now,
        source_weights={},
        swedish_sources=set(),
        breadth_weight=0.0,
        velocity_weight=0.0,
        swedish_weight=0.0,
        score_version="test-config",
        half_life_days=6,
        default_weight=2.0,
        previous_days=2,
    )

    assert result["score"] == pytest.approx(1.0)
    assert result["score_version"] == "test-config"

    metrics = result["score_breakdown"]["metrics"]
    assert metrics["previous_days"] == 2
    assert metrics["previous_count"] == 0
    assert metrics["contributions"][0]["source_weight"] == pytest.approx(2.0)
    assert metrics["contributions"][0]["time_weight"] == pytest.approx(0.5)


def test_calculate_topic_ranking_is_repeatable_without_changing_articles():
    now = datetime(2026, 11, 1, 12, tzinfo=timezone.utc)
    articles = [
        {
            "id": 1,
            "source": "IMY",
            "published": "2026-11-01T12:00:00Z",
        }
    ]
    original_articles = deepcopy(articles)
    options = {
        "source_weights": {"IMY": 3.0},
        "swedish_sources": {"IMY"},
        "breadth_weight": 0.5,
        "velocity_weight": 0.25,
        "swedish_weight": 1.0,
        "score_version": "test-v1",
    }

    first = calculate_topic_ranking(articles, now, **options)
    second = calculate_topic_ranking(articles, now, **options)

    assert first == second
    assert articles == original_articles
