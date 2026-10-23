import pytest

from src import draft_article
from src.draft_article import (
    add_byline,
    article_body,
    articles_from_summary,
    build_prompt,
    check_draft,
    count_sections,
    count_sentences,
    count_words,
    draft_stats,
    is_readable,
    main,
    parse_response,
    read_argument,
    read_summary,
)

SUMMARY = """<!-- model: claude-sonnet-5-5 | cost: $0.0140 -->

**AI-agenter i företag**

- Punkt ett.

Relevans för Novatech: Hög – agenter berör våra kunder.

Källor
- https://a.se/1
- https://b.se/2 (betalvägg)
- https://c.se/3 (sponsrad)
"""

ARGUMENT = "AI-agenter kan spara tid, men människan måste ha kontroll."


def make_article(words_per_section=150, sections=4):
    """A fake article in the expected format."""
    lines = ["# Rubrik", "", "Ingress med några ord.", ""]
    for i in range(1, sections + 1):
        lines += [f"## Avsnitt {i}", "", "ord " * words_per_section, ""]
    lines += ["## Källor", "- Källa A – https://a.se/1", "- Källa B – https://b.se/2"]
    return "\n".join(lines)


LINKEDIN = "Första meningen. Andra meningen! Tredje meningen? Läs mer: [LÄNK]"


def make_response(article=None, linkedin=LINKEDIN, notes="- En anteckning."):
    article = make_article() if article is None else article
    return (
        f"<article_draft>\n{article}\n</article_draft>\n"
        f"<linkedin_post>\n{linkedin}\n</linkedin_post>\n"
        f"<reviewer_notes>\n{notes}\n</reviewer_notes>"
    )


# -------------------- input


def test_read_summary_removes_comment(tmp_path):
    path = tmp_path / "summary.md"
    path.write_text(SUMMARY, encoding="utf-8")

    summary = read_summary(path)

    assert "<!--" not in summary
    assert summary.startswith("**AI-agenter")


def test_articles_from_summary_skips_sponsored_and_duplicates():
    summary = SUMMARY + "\nSe även https://a.se/1."

    articles = articles_from_summary(summary)

    assert [a["link"] for a in articles] == ["https://a.se/1", "https://b.se/2"]
    assert articles[0]["source"] == "a.se"


@pytest.mark.parametrize(
    ("article", "expected"),
    [
        ({"link": "x", "unread": False}, True),  # no --fetch
        ({"link": "x", "unread": True}, False),  # (ej läst) or (betalvägg)
        ({"link": "x", "unread": False, "text": "Brödtext"}, True),
        ({"link": "x", "unread": False, "text": None}, False),  # fetch failed
    ],
)
def test_is_readable(article, expected):
    assert is_readable(article) is expected


def test_read_argument_from_file_and_text(tmp_path):
    path = tmp_path / "arguments.txt"
    path.write_text("  Argument från fil.\n", encoding="utf-8")

    assert read_argument(path, None) == "Argument från fil."
    assert read_argument(None, " Argument i text ") == "Argument i text"
    assert read_argument(None, None) == ""


# -------------------- prompt


def test_build_prompt_contains_argument_summary_and_rules():
    prompt = build_prompt("Sammanfattning här", ARGUMENT, [])

    assert f"<ceo_argument>\n{ARGUMENT}\n</ceo_argument>" in prompt
    assert "<summary>\nSammanfattning här\n</summary>" in prompt
    assert "500–800 words" in prompt
    assert "[UNVERIFIED]" in prompt
    assert "(sponsrad)" in prompt
    assert 'Do not add any other "## " section' in prompt
    assert "also when they come from the CEO's argument" in prompt
    assert "only for factual claims" in prompt
    assert "never with new facts" in prompt
    assert "Figures and other measurable claims" in prompt
    assert "<source" not in prompt  # nothing fetched


def test_build_prompt_wraps_fetched_sources():
    articles = [
        {"link": "https://a.se/1", "text": "Brödtext"},
        {"link": "https://b.se/2", "text": None, "paywall": True},
    ]

    prompt = build_prompt("S", ARGUMENT, articles)

    assert prompt.count("<source id=") == 2
    assert "Text: Brödtext" in prompt
    assert "Text: Not available (paywall)" in prompt


# -------------------- answer


def test_parse_response_splits_three_parts():
    parts = parse_response(make_response(notes="- Notering"))

    assert parts["article"].startswith("# Rubrik")
    assert parts["linkedin"] == LINKEDIN
    assert parts["notes"] == "- Notering"


@pytest.mark.parametrize("tag", ["article_draft", "linkedin_post", "reviewer_notes"])
def test_parse_response_missing_part_raises(tag):
    response = make_response().replace(f"<{tag}>", "").replace(f"</{tag}>", "")

    with pytest.raises(ValueError, match=tag):
        parse_response(response)


def test_add_byline_goes_under_headline():
    result = add_byline("# Rubrik\n\nIngress.", "Kisslo")

    assert result == "# Rubrik\n\n*Av Kisslo*\n\nIngress."


def test_add_byline_without_headline_goes_first():
    assert add_byline("Ingress.", "Kisslo").startswith("*Av Kisslo*")


# -------------------- checks


def test_article_body_skips_headline_and_sources():
    body = article_body("# Rubrik\nText här\n## Källor\n- https://a.se/1")

    assert body == "Text här"


def test_count_words_ignores_markdown_and_tags():
    assert count_words("## Avsnitt\nEtt två [UNVERIFIED] tre-fyra.") == 4


def test_count_sections_ignores_source_list():
    assert count_sections(make_article(sections=3)) == 3


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (LINKEDIN, 4),  # "Läs mer: [LÄNK]" without a full stop counts too
        ("En mening.", 1),
        ("Version 2.5 är här. Bra!", 2),  # a dot inside a number is not an end
        ("", 0),
    ],
)
def test_count_sentences(text, expected):
    assert count_sentences(text) == expected


def test_check_draft_accepts_good_draft():
    parts = parse_response(make_response())
    articles = articles_from_summary(SUMMARY)

    assert check_draft(parts, articles) == []


def test_check_draft_allows_leaving_out_unread_source():
    # Real run 2026-10-23: The Register was (ej läst) and rightly left out.
    summary = "Källor\n- https://a.se/1\n- https://reg.com/x (ej läst)"
    article = make_article().replace("- Källa B – https://b.se/2", "")
    parts = parse_response(make_response(article=article))

    assert check_draft(parts, articles_from_summary(summary)) == []


def test_check_draft_still_requires_read_sources():
    summary = "Källor\n- https://a.se/1\n- https://c.se/3"
    parts = parse_response(make_response())  # lists a.se and b.se, not c.se

    warnings = "\n".join(check_draft(parts, articles_from_summary(summary)))

    assert "Source missing from 'Källor': https://c.se/3" in warnings
    assert "Link not in the sources (check it!): https://b.se/2" in warnings


def test_check_draft_warns_about_problems():
    parts = parse_response(
        make_response(
            article=make_article(words_per_section=50, sections=2)
            + "\n- https://invented.com/x",
            linkedin="En mening. Notes for reviewer: hemligt.",
        )
    )
    articles = articles_from_summary(SUMMARY)

    warnings = "\n".join(check_draft(parts, articles))

    assert "words" in warnings
    assert "2 sections" in warnings
    assert "sentences" in warnings
    assert "[LÄNK]" in warnings
    assert "leaked into the linkedin" in warnings
    assert "invented.com/x" in warnings


def test_draft_stats_counts_unverified_tags():
    article = make_article().replace("Ingress", "Ingress [UNVERIFIED]")
    parts = parse_response(make_response(article=article, linkedin="A [UNVERIFIED]."))

    assert draft_stats(parts)["unverified"] == 2


# -------------------- main


def run_main(monkeypatch, tmp_path, extra_args):
    summary = tmp_path / "summary.md"
    summary.write_text(SUMMARY, encoding="utf-8")
    monkeypatch.setattr(draft_article, "OUTPUT_DIR", tmp_path / "drafts")
    monkeypatch.setattr(
        "sys.argv",
        [
            "draft_article.py",
            "--summary",
            str(summary),
            "--argument-text",
            ARGUMENT,
            "--author",
            "Kisslo",
            *extra_args,
        ],
    )
    main()


def test_dry_run_works_without_api_key(monkeypatch, tmp_path, capsys):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(draft_article, "load_dotenv", lambda: None)

    run_main(monkeypatch, tmp_path, ["--dry-run"])

    out = capsys.readouterr().out
    assert ARGUMENT in out
    assert "Dry run: no call to Claude made." in out
    assert not (tmp_path / "drafts").exists()


def test_main_saves_three_separate_files(monkeypatch, tmp_path, capsys):
    calls = []

    def fake_call_claude(model, system_prompt, prompt, effort, max_tokens):
        calls.append(prompt)
        return make_response(notes="- Bara för granskaren."), 1000, 2000

    monkeypatch.setattr(draft_article, "call_claude", fake_call_claude)

    run_main(monkeypatch, tmp_path, [])

    assert len(calls) == 1
    folder = next((tmp_path / "drafts").iterdir())
    article = (folder / "article.md").read_text(encoding="utf-8")
    linkedin = (folder / "linkedin.md").read_text(encoding="utf-8")
    notes = (folder / "reviewer_notes.md").read_text(encoding="utf-8")
    assert article.startswith("# Rubrik\n\n*Av Kisslo*")
    assert "Bara för granskaren" not in article + linkedin
    assert "Bara för granskaren" in notes
    assert "No warnings" in notes
    assert "Saved to:" in capsys.readouterr().out


def test_main_saves_raw_answer_when_parts_are_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(
        draft_article, "call_claude", lambda *args: ("Inga taggar här", 10, 10)
    )

    with pytest.raises(SystemExit, match="Could not read the answer"):
        run_main(monkeypatch, tmp_path, [])

    folder = next((tmp_path / "drafts").iterdir())
    assert folder.name.startswith("failed_")
    assert (folder / "raw_response.md").read_text(encoding="utf-8") == "Inga taggar här"
