import numpy as np
import pytest

from src.embed_news import (
    article_text,
    find_similar_pairs,
    normalize_title,
)


def test_article_text_combines_title_and_description():
    article = {
        "title": "AI News",
        "description": "A new AI model was released.",
    }

    assert article_text(article) == ("AI News. A new AI model was released.")


def test_article_text_without_description():
    assert article_text({"title": "AI News"}) == "AI News"


def test_normalize_title_ignores_case_and_extra_spaces():
    assert normalize_title("  AI   NEWS  ") == "ai news"


def test_normalize_title_handles_missing_title():
    assert normalize_title(None) == ""


def test_find_similar_pairs_returns_most_similar_pair_first():
    articles = [
        {"title": "AI model released", "source": "Source A"},
        {"title": "New AI model launched", "source": "Source B"},
        {"title": "Football championship", "source": "Source C"},
    ]

    embeddings = np.array(
        [
            [1.0, 0.0],
            [0.9, np.sqrt(1 - 0.9**2)],
            [0.0, 1.0],
        ]
    )

    pairs = find_similar_pairs(articles, embeddings)

    assert len(pairs) == 3
    assert pairs[0][1:] == (0, 1)
    assert pairs[0][0] == pytest.approx(0.9)


def test_find_similar_pairs_ignores_identical_normalized_titles():
    articles = [
        {"title": "AI News", "source": "Source A"},
        {"title": "  AI NEWS  ", "source": "Source B"},
        {"title": "Different article", "source": "Source C"},
    ]

    embeddings = np.array(
        [
            [1.0, 0.0],
            [0.9, np.sqrt(1 - 0.9**2)],
            [0.0, 1.0],
        ]
    )

    pairs = find_similar_pairs(articles, embeddings)

    assert all(pair[1:] != (0, 1) for pair in pairs)


def test_find_similar_pairs_ignores_same_source():
    articles = [
        {"title": "AI News one", "source": "Source A"},
        {"title": "AI News two", "source": " source a "},
        {"title": "AI News three", "source": "Source B"},
    ]

    embeddings = np.array(
        [
            [1.0, 0.0],
            [0.9, np.sqrt(1 - 0.9**2)],
            [0.8, np.sqrt(1 - 0.8**2)],
        ]
    )

    pairs = find_similar_pairs(articles, embeddings)

    assert all(pair[1:] != (0, 1) for pair in pairs)


def test_find_similar_pairs_returns_each_pair_only_once():
    articles = [
        {"title": "Article A", "source": "Source A"},
        {"title": "Article B", "source": "Source B"},
    ]

    embeddings = np.array(
        [
            [1.0, 0.0],
            [0.9, np.sqrt(1 - 0.9**2)],
        ]
    )

    pairs = find_similar_pairs(articles, embeddings)

    assert len(pairs) == 1
    assert pairs[0][1:] == (0, 1)
