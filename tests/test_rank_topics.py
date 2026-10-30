from rank_topics import count_distinct_sources


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
