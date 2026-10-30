import numpy as np

from src.group_news import (
    article_text,
    build_groups,
    clusters_within_date_window,
    deduplicate_articles,
    normalize_title,
    normalize_url,
    parse_published,
)


def test_normalize_url_removes_tracking_parameters():
    url = "https://www.example.com/article?utm_source=test&id=123&fbclid=abc"

    result = normalize_url(url)

    assert result == "https://example.com/article?id=123"


def test_normalize_url_removes_trailing_slash():
    assert normalize_url("https://example.com/news/") == ("https://example.com/news")


def test_normalize_title_ignores_case_and_extra_spaces():
    assert normalize_title("  AI   NEWS  ") == "ai news"


def test_article_text_combines_title_and_description():
    article = {
        "title": "AI News",
        "description": "New AI model released.",
    }

    assert article_text(article) == "AI News. New AI model released."


def test_article_text_without_description():
    assert article_text({"title": "AI News"}) == "AI News"


def test_parse_published_converts_utc_date():
    result = parse_published("2026-10-20T12:00:00Z")

    assert result is not None
    assert result.isoformat() == "2026-10-20T12:00:00+00:00"


def test_parse_published_handles_missing_date():
    assert parse_published(None) is None


def test_parse_published_handles_invalid_date():
    assert parse_published("not-a-date") is None


def test_clusters_within_date_window_accepts_seven_days():
    dates = [
        parse_published("2026-10-20T12:00:00Z"),
        parse_published("2026-10-27T12:00:00Z"),
    ]

    assert clusters_within_date_window([0], [1], dates)


def test_clusters_within_date_window_rejects_more_than_seven_days():
    dates = [
        parse_published("2026-10-20T12:00:00Z"),
        parse_published("2026-10-28T12:00:00Z"),
    ]

    assert not clusters_within_date_window([0], [1], dates)


def test_deduplicate_articles_keeps_longest_version():
    articles = [
        {
            "title": "AI News",
            "link": "https://example.com/news?utm_source=one",
            "source": "Example",
            "description": "Short",
        },
        {
            "title": "AI News",
            "link": "https://example.com/news?utm_source=two",
            "source": "Example",
            "description": "A much longer description of the same article.",
        },
    ]

    result = deduplicate_articles(articles)

    assert len(result) == 1
    assert result[0]["description"] == (
        "A much longer description of the same article."
    )


def test_deduplicate_articles_skips_missing_titles():
    articles = [
        {"title": "", "link": "https://example.com/1"},
        {"title": "Valid article", "link": "https://example.com/2"},
    ]

    result = deduplicate_articles(articles)

    assert len(result) == 1
    assert result[0]["title"] == "Valid article"


def make_article(title, source, published="2026-10-20T12:00:00Z"):
    return {
        "title": title,
        "source": source,
        "published": published,
        "description": "Test description",
    }


def test_build_groups_groups_similar_articles_from_different_sources():
    articles = [
        make_article("AI model released", "Source A"),
        make_article("New AI model launched", "Source B"),
    ]

    embeddings = np.array(
        [
            [1.0, 0.0],
            [0.9, np.sqrt(1 - 0.9**2)],
        ]
    )

    groups = build_groups(articles, embeddings)

    assert len(groups) == 1
    assert groups[0]["article_count"] == 2
    assert groups[0]["source_count"] == 2


def test_build_groups_does_not_group_unrelated_articles():
    articles = [
        make_article("AI model released", "Source A"),
        make_article("Football championship results", "Source B"),
    ]

    embeddings = np.array(
        [
            [1.0, 0.0],
            [0.0, 1.0],
        ]
    )

    groups = build_groups(articles, embeddings)

    assert groups == []


def test_build_groups_prevents_weak_links_between_groups():
    angles = np.radians([0, 40, 80])

    embeddings = np.column_stack(
        [
            np.cos(angles),
            np.sin(angles),
        ]
    )

    articles = [
        make_article("AI event A", "Source A"),
        make_article("AI event B", "Source B"),
        make_article("AI event C", "Source C"),
    ]

    groups = build_groups(articles, embeddings)

    assert len(groups) == 1
    assert groups[0]["article_count"] == 2


def test_build_groups_rejects_articles_more_than_seven_days_apart():
    articles = [
        make_article(
            "AI model released",
            "Source A",
            "2026-10-20T12:00:00Z",
        ),
        make_article(
            "New AI model launched",
            "Source B",
            "2026-10-28T12:00:00Z",
        ),
    ]

    embeddings = np.array(
        [
            [1.0, 0.0],
            [0.9, np.sqrt(1 - 0.9**2)],
        ]
    )

    groups = build_groups(articles, embeddings)

    assert groups == []


def test_build_groups_does_not_group_articles_from_same_source():
    articles = [
        make_article("AI model released", "Source A"),
        make_article("New AI model launched", "Source A"),
    ]

    embeddings = np.array(
        [
            [1.0, 0.0],
            [0.9, np.sqrt(1 - 0.9**2)],
        ]
    )

    groups = build_groups(articles, embeddings)

    assert groups == []


def test_build_groups_does_not_merge_identical_normalized_titles():
    articles = [
        make_article("New AI Model Released", "Source A"),
        make_article("  NEW AI MODEL RELEASED  ", "Source B"),
    ]

    embeddings = np.array(
        [
            [1.0, 0.0],
            [0.9, np.sqrt(1 - 0.9**2)],
        ]
    )

    groups = build_groups(articles, embeddings)

    assert groups == []
