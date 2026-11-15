import pytest

import draft_article
from content_tools import ClaudeError
from draft_article import (
    STYLE_GUIDE,
    add_byline,
    article_body,
    build_draft_prompt,
    check_draft,
    check_inputs,
    count_sections,
    count_sentences,
    count_words,
    draft_stats,
    find_topic,
    main,
    parse_response,
    source_news_ids,
    write_draft,
)

ANGLE = "Småföretag ska inte vänta på EU, de kan börja redan nu."

TOPIC = {
    "id": 7,
    "label": "EU ger småföretag vägledning om AI-förordningen",
    "why_relevant_sv": "Småföretag får tydligare besked om kraven.",
    "articles": [
        {
            "news_id": 11,
            "title": "EU guidance for small businesses",
            "source": "Källa A",
            "link": "https://a.se/1",
            "description": "The Commission released guidance.",
        },
        {
            "news_id": 12,
            "title": "Nya regler för AI",
            "source": "Källa B",
            "link": "https://b.se/2",
            "description": "",
        },
    ],
}


def make_article(words_per_section=150, sections=4):
    """A fake article in the expected format."""
    lines = ["# Rubrik", "", "Ingress med några ord.", ""]
    for i in range(1, sections + 1):
        lines += [f"## Avsnitt {i}", "", "ord " * words_per_section, ""]
    lines += [
        "## Källor",
        "- Källa A: EU guidance – https://a.se/1",
        "- Källa B: Nya regler – https://b.se/2",
    ]
    return "\n".join(lines)


LINKEDIN = "Första meningen. Andra meningen! Tredje meningen? Läs mer: [LÄNK]"


def make_response(article=None, linkedin=LINKEDIN, notes="- En anteckning."):
    article = make_article() if article is None else article
    return (
        f"<article_draft>\n{article}\n</article_draft>\n"
        f"<linkedin_post>\n{linkedin}\n</linkedin_post>\n"
        f"<reviewer_notes>\n{notes}\n</reviewer_notes>"
    )


def fake_call(response, calls=None):
    """A stand-in for call_claude that records the prompts it gets."""

    def call(model, system_prompt, prompt, effort, max_tokens):
        if calls is not None:
            calls.append(prompt)
        return response, 1000, 2000

    return call


# -------------------- input


def test_check_inputs_accepts_good_topic():
    check_inputs(TOPIC, ANGLE, "agree")
    check_inputs(TOPIC, ANGLE, "rebut")


@pytest.mark.parametrize(
    ("topic", "angle", "stance", "message"),
    [
        (TOPIC, "  ", "agree", "angle is empty"),
        (TOPIC, "x" * 2001, "agree", "longer than"),
        (TOPIC, ANGLE, "maybe", "Stance must be"),
        ({**TOPIC, "label": ""}, ANGLE, "agree", "has no label"),
        ({**TOPIC, "articles": []}, ANGLE, "agree", "has no articles"),
        ({**TOPIC, "articles": [{"news_id": 1}]}, ANGLE, "agree", "has no link"),
    ],
)
def test_check_inputs_rejects_bad_inputs(topic, angle, stance, message):
    with pytest.raises(ValueError, match=message):
        check_inputs(topic, angle, stance)


def test_source_news_ids_keeps_rank_order():
    assert source_news_ids(TOPIC) == [11, 12]


# -------------------- prompt


def test_build_draft_prompt_contains_angle_topic_sources_and_rules():
    prompt = build_draft_prompt(TOPIC, ANGLE, "agree")

    assert f"<kisslo_angle>\n{ANGLE}\n</kisslo_angle>" in prompt
    assert "Stance: agree. Kisslo agrees" in prompt
    assert "Label: EU ger småföretag vägledning om AI-förordningen" in prompt
    assert '<source id="11">' in prompt
    assert "Link: https://a.se/1" in prompt
    assert "Description: No description" in prompt  # article 12 has none
    assert "500–800 words" in prompt
    assert "[UNVERIFIED]" in prompt
    assert "never add other links" in prompt
    assert "also when they come from Kisslo's angle" in prompt
    assert "never with new facts" in prompt


def test_build_draft_prompt_includes_style_guide():
    prompt = build_draft_prompt(TOPIC, ANGLE, "agree")

    assert STYLE_GUIDE in prompt
    for rule in ("No contrast phrasing", "No consultant buzzwords", "No repetition"):
        assert rule in prompt
    assert "Swedish SME angle" in prompt


def test_build_draft_prompt_rebut_keeps_facts():
    prompt = build_draft_prompt(TOPIC, ANGLE, "rebut")

    assert "Stance: rebut." in prompt
    assert "do not invent counter-evidence" in prompt


# -------------------- answer


def test_parse_response_splits_three_parts():
    parts = parse_response(make_response(notes="- Notering."))

    assert parts["article"].startswith("# Rubrik")
    assert parts["linkedin"] == LINKEDIN
    assert parts["notes"] == "- Notering."


@pytest.mark.parametrize("tag", ["article_draft", "linkedin_post", "reviewer_notes"])
def test_parse_response_missing_part_raises(tag):
    response = make_response().replace(f"<{tag}>", "").replace(f"</{tag}>", "")

    with pytest.raises(ValueError, match=tag):
        parse_response(response)


def test_add_byline_goes_under_headline():
    assert add_byline("# Rubrik\n\nText", "Kisslo") == "# Rubrik\n\n*Av Kisslo*\n\nText"


def test_add_byline_without_headline_goes_first():
    assert add_byline("Text", "Kisslo") == "*Av Kisslo*\n\nText"


# -------------------- checks


def test_article_body_skips_headline_and_sources():
    body = article_body(make_article(words_per_section=1, sections=1))

    assert "Rubrik" not in body
    assert "https://a.se/1" not in body


def test_count_words_ignores_markdown_and_tags():
    assert count_words("## Två ord [UNVERIFIED] **tre**") == 3


def test_count_sections_ignores_source_list():
    assert count_sections(make_article(sections=3)) == 3


@pytest.mark.parametrize(
    ("text", "expected"),
    [(LINKEDIN, 4), ("En mening utan punkt", 1), ("", 0)],
)
def test_count_sentences(text, expected):
    assert count_sentences(text) == expected


def test_check_draft_accepts_good_draft():
    parts = parse_response(make_response())

    assert check_draft(parts, TOPIC["articles"]) == []


def test_check_draft_warns_about_problems():
    article = make_article(words_per_section=10, sections=2).replace("# Rubrik", "")
    article += "\n- Extra – https://other.se/x"
    linkedin = "En mening. Se https://a.se/1 Notes for reviewer"
    parts = parse_response(make_response(article=article, linkedin=linkedin))

    warnings = "\n".join(check_draft(parts, TOPIC["articles"]))

    assert "words" in warnings
    assert "2 sections" in warnings
    assert "no '# ' headline" in warnings
    assert "no [LÄNK]" in warnings
    assert "leaked into the linkedin" in warnings
    assert "Link not in the sources (check it!): https://other.se/x" in warnings
    assert "LinkedIn post: Link not in the sources" not in warnings  # a.se/1 is ok
    assert "Source missing" not in warnings


def test_check_draft_warns_about_missing_source():
    article = make_article().replace("- Källa B: Nya regler – https://b.se/2", "")
    parts = parse_response(make_response(article=article))

    assert check_draft(parts, TOPIC["articles"]) == [
        "Source missing from 'Källor': https://b.se/2"
    ]


def test_draft_stats_counts_unverified_tags():
    article = make_article().replace("Ingress", "Ingress [UNVERIFIED]")
    parts = parse_response(make_response(article=article, linkedin="A [UNVERIFIED]."))

    assert draft_stats(parts)["unverified"] == 2


# -------------------- write_draft


def test_write_draft_returns_checked_draft():
    calls = []

    draft = write_draft(TOPIC, ANGLE, call=fake_call(make_response(), calls))

    assert len(calls) == 1
    assert STYLE_GUIDE in calls[0]
    assert draft["article"].startswith("# Rubrik")
    assert draft["linkedin"] == LINKEDIN
    assert draft["notes"] == "- En anteckning."
    assert draft["warnings"] == []
    assert draft["source_news_ids"] == [11, 12]
    assert (draft["tokens_in"], draft["tokens_out"]) == (1000, 2000)
    assert draft["cost"] == pytest.approx(0.022)  # sonnet 5.5: 2 in, 10 out per MTok


def test_write_draft_checks_inputs_before_calling_claude():
    calls = []

    with pytest.raises(ValueError, match="angle is empty"):
        write_draft(TOPIC, " ", call=fake_call(make_response(), calls))
    assert calls == []


def test_write_draft_raises_when_parts_are_missing():
    with pytest.raises(ValueError, match="Could not read the answer"):
        write_draft(TOPIC, ANGLE, call=fake_call("Inga taggar här"))


# -------------------- main


def run_main(monkeypatch, tmp_path, extra_args):
    monkeypatch.setattr(draft_article, "OUTPUT_DIR", tmp_path / "drafts")
    monkeypatch.setattr(draft_article, "load_dotenv", lambda: None)
    monkeypatch.setattr(
        "sys.argv",
        ["draft_article.py", "--topic-id", "101", "--angle", ANGLE, *extra_args],
    )
    main()


def test_find_topic_reads_example_file():
    topic = find_topic(101)

    assert topic["label"]
    assert topic["articles"]


def test_find_topic_unknown_id_exits():
    with pytest.raises(SystemExit, match="Topic 999 is not in"):
        find_topic(999)


def test_dry_run_works_without_api_key(monkeypatch, tmp_path, capsys):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    run_main(monkeypatch, tmp_path, ["--dry-run"])

    out = capsys.readouterr().out
    assert ANGLE in out
    assert "No contrast phrasing" in out
    assert "Dry run: no call to Claude made." in out
    assert not (tmp_path / "drafts").exists()


def test_main_saves_three_separate_files(monkeypatch, tmp_path, capsys):
    topic = find_topic(101)
    article = "\n".join(
        [make_article().split("## Källor")[0], "## Källor"]
        + [f"- {a['source']}: {a['title']} – {a['link']}" for a in topic["articles"]]
    )
    monkeypatch.setattr(
        draft_article,
        "call_claude",
        fake_call(make_response(article=article, notes="- Bara för granskaren.")),
    )

    run_main(monkeypatch, tmp_path, ["--author", "Kisslo"])

    folder = next((tmp_path / "drafts").iterdir())
    article_md = (folder / "article.md").read_text(encoding="utf-8")
    linkedin = (folder / "linkedin.md").read_text(encoding="utf-8")
    notes = (folder / "reviewer_notes.md").read_text(encoding="utf-8")
    assert article_md.startswith("# Rubrik\n\n*Av Kisslo*")
    assert "Bara för granskaren" not in article_md + linkedin
    assert "Bara för granskaren" in notes
    assert "No warnings" in notes
    assert "Stance: agree" in notes
    assert "Saved to:" in capsys.readouterr().out


def test_main_exits_cleanly_on_claude_error(monkeypatch, tmp_path):
    def failing_call(*args):
        raise ClaudeError("Rate limit reached. Wait a minute and try again.")

    monkeypatch.setattr(draft_article, "call_claude", failing_call)

    with pytest.raises(SystemExit, match="Rate limit reached"):
        run_main(monkeypatch, tmp_path, [])
    assert not (tmp_path / "drafts").exists()
