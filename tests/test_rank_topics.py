import pytest

from rank_topics import calculate_time_decay, count_distinct_sources


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
