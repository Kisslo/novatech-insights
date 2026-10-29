import json

import pytest

from src.label_topics import (
    DEFAULT_FIXTURE,
    build_prompt,
    estimate_run_cost,
    load_fixture,
    main,
    normalize_topic,
    render_markdown,
    select_top,
)


def make_topic(topic_id, score, n_articles=3, **extra):
    articles = [
        {
            "news_id": topic_id * 10 + i,
            "title": f"Title {topic_id}-{i}",
            "source": f"Source {i}",
            "link": f"https://example.com/{topic_id}/{i}",
            "description": f"Description {topic_id}-{i}",
        }
        for i in range(n_articles)
    ]
    return {"id": topic_id, "score": score, "articles": articles, **extra}


# -------------------- input


def test_sample_fixture_loads_with_required_fields():
    topics = load_fixture(DEFAULT_FIXTURE)

    assert len(topics) == 6
    for topic in topics:
        assert 1 <= len(topic["articles"]) <= 3
        for article in topic["articles"]:
            assert article["news_id"]
            assert article["link"].startswith("https://")


def test_counts_from_read_interface_are_kept():
    topic = normalize_topic(make_topic(1, 0.5, article_count=10, source_count=4))

    assert topic["article_count"] == 10
    assert topic["source_count"] == 4
    assert topic["counts_from_articles"] is False


def test_missing_counts_are_counted_from_articles():
    raw = make_topic(1, 0.5, n_articles=2)
    raw["articles"][1]["source"] = raw["articles"][0]["source"]

    topic = normalize_topic(raw)

    assert topic["article_count"] == 2
    assert topic["source_count"] == 1
    assert topic["counts_from_articles"] is True


def test_only_three_articles_are_kept_in_order():
    topic = normalize_topic(make_topic(1, 0.5, n_articles=5))

    assert [a["news_id"] for a in topic["articles"]] == [10, 11, 12]


def test_missing_description_becomes_empty_string():
    raw = make_topic(1, 0.5, n_articles=1)
    del raw["articles"][0]["description"]

    assert normalize_topic(raw)["articles"][0]["description"] == ""


@pytest.mark.parametrize("field", ["id", "score", "articles"])
def test_topic_without_required_field_is_rejected(field):
    raw = make_topic(1, 0.5)
    del raw[field]

    with pytest.raises(ValueError, match=field):
        normalize_topic(raw)


def test_article_without_link_is_rejected():
    raw = make_topic(7, 0.5)
    raw["articles"][0]["link"] = ""

    with pytest.raises(ValueError, match="topic 7 has no 'link'"):
        normalize_topic(raw)


def test_select_top_sorts_by_score_and_breaks_ties_by_id():
    topics = [
        normalize_topic(make_topic(3, 0.5)),
        normalize_topic(make_topic(1, 0.9)),
        normalize_topic(make_topic(2, 0.5)),
    ]

    assert [t["id"] for t in select_top(topics, 5)] == [1, 2, 3]
    assert [t["id"] for t in select_top(topics, 2)] == [1, 2]


# -------------------- prompt


def test_prompt_wraps_articles_and_leaves_out_score_and_links():
    topic = normalize_topic(make_topic(1, 0.987))

    prompt = build_prompt(topic)

    assert prompt.count("<article id=") == 3
    assert "Title: Title 1-0" in prompt
    assert "0.987" not in prompt
    assert "https://" not in prompt


def test_prompt_skips_empty_description():
    raw = make_topic(1, 0.5, n_articles=1)
    raw["articles"][0]["description"] = ""

    assert "Description:" not in build_prompt(normalize_topic(raw))


def test_run_cost_for_twenty_topics_is_below_limit():
    topic = normalize_topic(make_topic(1, 0.5))
    prompts = [build_prompt(topic)] * 20

    assert estimate_run_cost("claude-sonnet-5-5", prompts) < 0.5
    assert estimate_run_cost("unknown-model", prompts) is None


# -------------------- output


def test_markdown_shows_rank_counts_links_and_news_id():
    topics = [normalize_topic(make_topic(1, 0.91, article_count=7, source_count=4))]
    labels = {
        1: {
            "label": "Ny AI-vägledning",
            "why_relevant_sv": "Viktigt för småföretag.",
            "llm_relevance": 4,
        }
    }

    text = render_markdown(topics, labels, 20, "fixture")

    assert "## 1. Ny AI-vägledning" in text
    assert "Poäng: 0.91 · Källor: 4 · Artiklar: 7 · AI-relevans: 4/5" in text
    assert "Viktigt för småföretag." in text
    assert "- [Title 1-0](https://example.com/1/0) – Source 0 (news_id 10)" in text


def test_markdown_placeholders_and_counted_values():
    topics = [normalize_topic(make_topic(1, 0.5, n_articles=2))]

    text = render_markdown(topics, {}, 5, "fixture")

    assert "## 1. (rubrik skrivs av Claude)" in text
    assert "AI-relevans: –" in text
    assert "Källor: minst 2 · Artiklar: minst 2" in text


# -------------------- main


def test_dry_run_prints_prompts_and_preview(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["label_topics.py", "--top", "2", "--dry-run"])

    def no_call(*args, **kwargs):
        raise AssertionError("Claude must not be called in a dry run")

    monkeypatch.setattr("content_tools.call_claude", no_call)

    main()

    out = capsys.readouterr().out
    assert out.count("--- Prompt for topic") == 2
    assert "Estimated cost for 2 calls" in out
    assert "## 1. (rubrik skrivs av Claude)" in out
    assert "## 2. (rubrik skrivs av Claude)" in out
    assert "## 3." not in out


def test_dry_run_reports_fewer_topics_than_asked(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["label_topics.py", "--dry-run"])

    main()

    assert "Only 6 topics available (asked for 20)." in capsys.readouterr().out


def test_broken_fixture_stops_with_clear_message(tmp_path, monkeypatch):
    path = tmp_path / "topics.json"
    path.write_text(json.dumps({"topics": [{"id": 1}]}), encoding="utf-8")
    monkeypatch.setattr(
        "sys.argv", ["label_topics.py", "--fixture", str(path), "--dry-run"]
    )

    with pytest.raises(SystemExit) as stopped:
        main()

    assert "Could not read topics" in str(stopped.value)
