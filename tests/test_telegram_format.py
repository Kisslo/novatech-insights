import re

import pytest

from telegram_format import (
    MAX_CALLBACK_BYTES,
    MAX_MESSAGE_CHARS,
    MAX_TITLE_CHARS,
    callback_data,
    escape_attribute,
    escape_html,
    format_topic,
    is_web_link,
    shorten,
)


def make_topic(**changes):
    topic = {
        "id": 101,
        "score": 0.91,
        "label": "EU ger småföretag vägledning om AI-förordningen",
        "why_relevant_sv": "Små företag får tydligare besked om kraven.",
        "llm_relevance": 4,
        "article_count": 7,
        "source_count": 4,
        "counts_from_articles": False,
        "articles": [
            {
                "news_id": 1001,
                "title": "EU publishes guidance",
                "source": "Example Tech News",
                "link": "https://example.com/a",
            },
            {
                "news_id": 1002,
                "title": "Nya regler för AI",
                "source": "Exempel Affärer",
                "link": "https://example.com/b",
            },
        ],
    }
    topic.update(changes)
    return topic


# -------------------- escaping


def test_escape_html_escapes_ampersand_first():
    assert escape_html("A & B <b> x > y") == "A &amp; B &lt;b&gt; x &gt; y"
    assert escape_html("&lt;") == "&amp;lt;"


def test_escape_attribute_also_escapes_double_quote():
    assert escape_attribute('a"b&c') == "a&quot;b&amp;c"


def test_text_from_sources_cannot_add_tags():
    topic = make_topic(
        label="Fakturor & <script>bokslut</script>",
        articles=[
            {
                "news_id": 1,
                "title": '<a href="https://evil.example">Klicka</a>',
                "source": "R&D <News>",
                "link": "https://example.com/a?x=1&y=2",
            }
        ],
    )
    text = format_topic(topic, 1)["text"]
    assert "Fakturor &amp; &lt;script&gt;bokslut&lt;/script&gt;" in text
    assert '&lt;a href="https://evil.example"&gt;' in text
    assert "R&amp;D &lt;News&gt;" in text
    assert 'href="https://example.com/a?x=1&amp;y=2"' in text
    # Only our own tags are left: one <b> and one link
    assert text.count("<b>") == 1
    assert text.count("<a ") == 1


# -------------------- message content


def test_format_topic_builds_text_and_buttons():
    message = format_topic(make_topic(), 1)
    assert message["topic_id"] == 101
    assert message["rank"] == 1
    assert message["parse_mode"] == "HTML"
    assert message["text"].startswith(
        "<b>1. EU ger småföretag vägledning om AI-förordningen</b>"
    )
    assert "Poäng: 0.91 · Källor: 4 · Artiklar: 7 · AI-relevans: 4/5" in message["text"]
    assert (
        '• <a href="https://example.com/a">EU publishes guidance</a>'
        " – Example Tech News"
    ) in message["text"]
    assert message["buttons"] == [
        {"text": "Skriv", "callback_data": "write:101"},
        {"text": "Skippa", "callback_data": "skip:101"},
    ]
    assert "reply_markup" not in message


def test_counts_from_articles_are_shown_as_at_least():
    text = format_topic(make_topic(counts_from_articles=True), 1)["text"]
    assert "Källor: minst 4 · Artiklar: minst 7" in text


@pytest.mark.parametrize(
    "score, expected",
    [(0.91, "0.91"), (0, "0.00"), (0.0, "0.00"), (12.3456, "12.35"), (3, "3.00")],
)
def test_score_is_shown_with_two_decimals(score, expected):
    text = format_topic(make_topic(score=score), 1)["text"]
    assert f"Poäng: {expected} · Källor: 4" in text


@pytest.mark.parametrize("score", [None, "0.91", True, float("nan"), float("inf")])
def test_topic_without_usable_score_raises(score):
    with pytest.raises(ValueError, match="score"):
        format_topic(make_topic(score=score), 1)


def test_topic_with_missing_score_raises():
    topic = make_topic()
    del topic["score"]
    with pytest.raises(ValueError, match="has no score"):
        format_topic(topic, 1)


def test_non_web_link_is_not_clickable():
    topic = make_topic(
        articles=[
            {
                "news_id": 1,
                "title": "Titel",
                "source": "Källa",
                "link": "javascript:alert(1)",
            }
        ]
    )
    text = format_topic(topic, 1)["text"]
    assert "<a " not in text
    assert "• Titel – Källa" in text


@pytest.mark.parametrize(
    "link, expected",
    [
        ("https://example.com/a", True),
        ("http://example.com", True),
        ("javascript:alert(1)", False),
        ("ftp://example.com/file", False),
        ("https://", False),
        ("example.com/a", False),
    ],
)
def test_is_web_link(link, expected):
    assert is_web_link(link) is expected


# -------------------- Telegram limits


def test_long_texts_are_shortened_below_the_message_limit():
    long_title = "Ord " * 1000
    topic = make_topic(
        label="Rubrik " * 200,
        why_relevant_sv="Mening " * 500,
        articles=[
            {
                "news_id": i,
                "title": long_title,
                "source": "Källa " * 100,
                "link": "https://example.com/" + "a" * 300,
            }
            for i in range(3)
        ],
    )
    text = format_topic(topic, 1)["text"]
    assert len(text) <= MAX_MESSAGE_CHARS
    assert "…" in text


def test_long_title_is_cut_before_escaping():
    # If the text were escaped first, the cut could land inside "&amp;"
    topic = make_topic(
        articles=[
            {
                "news_id": 1,
                "title": "&" * 300,
                "source": "Källa",
                "link": "https://example.com/a",
            }
        ]
    )
    text = format_topic(topic, 1)["text"]
    assert "&amp;" * (MAX_TITLE_CHARS - 1) + "…</a>" in text
    # Every & in the text starts a complete entity
    assert not re.search(r"&(?!amp;|lt;|gt;|quot;)", text)


def test_shorten_collapses_whitespace():
    assert shorten("  a\n\n b\t c ", 50) == "a b c"


def test_too_long_message_raises(monkeypatch):
    monkeypatch.setattr("telegram_format.MAX_MESSAGE_CHARS", 50)
    with pytest.raises(ValueError, match="too long"):
        format_topic(make_topic(), 1)


def test_callback_data_fits_for_largest_bigint():
    largest_bigint = 2**63 - 1
    data = callback_data("write", largest_bigint)
    assert len(data.encode("utf-8")) <= MAX_CALLBACK_BYTES


def test_callback_data_over_64_bytes_raises():
    with pytest.raises(ValueError, match="64 bytes"):
        callback_data("x" * 60, 12345)


# -------------------- missing labels


@pytest.mark.parametrize(
    "changes",
    [
        {"label": None},
        {"label": "   "},
        {"why_relevant_sv": ""},
        {"llm_relevance": None},
        {"llm_relevance": True},
        {"llm_relevance": 0},
        {"llm_relevance": 6},
        {"llm_relevance": "4"},
    ],
)
def test_unlabelled_topic_raises(changes):
    with pytest.raises(ValueError, match="topic 101"):
        format_topic(make_topic(**changes), 1)
