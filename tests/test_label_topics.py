import json

import pytest

from content_tools import ClaudeError
from src.label_topics import (
    DEFAULT_FIXTURE,
    build_prompt,
    estimate_run_cost,
    load_fixture,
    main,
    normalize_topic,
    parse_label_reply,
    render_markdown,
    select_top,
)

GOOD_REPLY = (
    '{"label": "Ny AI-vägledning", '
    '"why_relevant_sv": "Viktigt för småföretag.", "llm_relevance": 4}'
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


# -------------------- Claude reply


def test_parse_reply_reads_all_fields():
    assert parse_label_reply(GOOD_REPLY) == {
        "label": "Ny AI-vägledning",
        "why_relevant_sv": "Viktigt för småföretag.",
        "llm_relevance": 4,
    }


def test_parse_reply_accepts_code_fence_and_tidies_whitespace():
    reply = (
        '```json\n{"label": "  Ny   rubrik ", "why_relevant_sv": "En\\nmening.", '
        '"llm_relevance": 2}\n```'
    )

    result = parse_label_reply(reply)

    assert result["label"] == "Ny rubrik"
    assert result["why_relevant_sv"] == "En mening."


@pytest.mark.parametrize(
    ("reply", "reason"),
    [
        ("Sorry, I cannot help.", "no JSON object"),
        ('{"label": "A", "why_relevant_sv": "B", "llm_relevance": }', "not valid"),
        ('{"why_relevant_sv": "B", "llm_relevance": 3}', "'label'"),
        ('{"label": " ", "why_relevant_sv": "B", "llm_relevance": 3}', "'label'"),
        ('{"label": "A", "why_relevant_sv": "", "llm_relevance": 3}', "why_relevant"),
        ('{"label": "A", "why_relevant_sv": "B", "llm_relevance": 6}', "between"),
        ('{"label": "A", "why_relevant_sv": "B", "llm_relevance": 0}', "between"),
        ('{"label": "A", "why_relevant_sv": "B", "llm_relevance": 3.5}', "whole"),
        ('{"label": "A", "why_relevant_sv": "B", "llm_relevance": "4"}', "whole"),
        ('{"label": "A", "why_relevant_sv": "B", "llm_relevance": true}', "whole"),
    ],
)
def test_parse_reply_rejects_unusable_answers(reply, reason):
    with pytest.raises(ValueError, match=reason):
        parse_label_reply(reply)


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


def test_markdown_marks_failed_topic_with_its_error():
    topics = [normalize_topic(make_topic(1, 0.5)), normalize_topic(make_topic(2, 0.4))]

    text = render_markdown(topics, {}, 20, "fixture", {2: "Rate limit reached."})

    assert "## 2. (rubrik saknas)" in text
    assert "Fel: Rate limit reached." in text
    assert "Misslyckade ämnen: 1" in text


# -------------------- main


def test_dry_run_prints_prompts_and_preview(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["label_topics.py", "--top", "2", "--dry-run"])

    def no_call(*args, **kwargs):
        raise AssertionError("Claude must not be called in a dry run")

    monkeypatch.setattr("src.label_topics.call_claude", no_call)

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


# -------------------- real run (Claude is always mocked)


def fake_claude(replies):
    """Return a stand-in for call_claude that answers from a list, in order."""
    answers = iter(replies)

    def call(model, system_prompt, prompt, effort, max_tokens):
        answer = next(answers)
        if isinstance(answer, Exception):
            raise answer
        return answer, 300, 100

    return call


def test_run_saves_list_and_continues_after_failed_topics(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.setattr("src.label_topics.OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(
        "src.label_topics.call_claude",
        fake_claude([GOOD_REPLY, ClaudeError("Rate limit reached."), "not json"]),
    )
    monkeypatch.setattr("sys.argv", ["label_topics.py", "--top", "3"])

    main()

    out = capsys.readouterr().out
    assert "FAILED topic 102: Rate limit reached." in out
    assert "FAILED topic 103: invalid answer" in out
    assert "Labelled: 1 of 3" in out
    saved = list(tmp_path.glob("top3_*.md"))
    assert len(saved) == 1
    text = saved[0].read_text(encoding="utf-8")
    assert "## 1. Ny AI-vägledning" in text
    assert "AI-relevans: 4/5" in text
    assert "## 2. (rubrik saknas)" in text
    assert "(news_id 1001)" in text
    assert "<!-- model:" in text


def test_run_saves_nothing_when_every_topic_fails(tmp_path, monkeypatch):
    monkeypatch.setattr("src.label_topics.OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(
        "src.label_topics.call_claude",
        fake_claude([ClaudeError("ANTHROPIC_API_KEY is missing.")] * 2),
    )
    monkeypatch.setattr("sys.argv", ["label_topics.py", "--top", "2"])

    with pytest.raises(SystemExit) as stopped:
        main()

    assert "nothing was saved" in str(stopped.value)
    assert list(tmp_path.iterdir()) == []


def test_run_stops_before_calls_when_cost_is_too_high(tmp_path, monkeypatch):
    monkeypatch.setattr("src.label_topics.OUTPUT_DIR", tmp_path)
    monkeypatch.setattr("src.label_topics.MAX_COST_USD", 0.0001)
    monkeypatch.setattr("src.label_topics.call_claude", fake_claude([]))
    monkeypatch.setattr("sys.argv", ["label_topics.py", "--top", "2"])

    with pytest.raises(SystemExit) as stopped:
        main()

    assert "above the limit" in str(stopped.value)
