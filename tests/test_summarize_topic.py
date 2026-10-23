import pytest

from src.summarize_topic import (
    build_prompt,
    main,
    parse_rows,
    select_articles,
    sort_newest_first,
)

# -------------------- rows


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("1", [1]),
        ("1,2,3", [1, 2, 3]),
        (" 234, 289 ,469 ", [234, 289, 469]),
        ("1,,2", [1, 2]),
    ],
)
def test_parse_rows_valid(value, expected):
    assert parse_rows(value) == expected


@pytest.mark.parametrize("value", ["abc", "1,x", "-1", "", ","])
def test_parse_rows_invalid(value):
    with pytest.raises(ValueError):
        parse_rows(value)


# -------------------- selection

ARTICLES = [
    {"title": "AI agents at work", "link": "https://a.se/1", "subject": "AI"},
    {"title": "New cloud region", "link": "https://b.se/2", "subject": "Cloud"},
    {"title": "Agent tools", "link": "https://c.se/3", "subject": "ai"},
    {"title": "No link", "link": "", "subject": "AI"},
]


def test_select_by_subject_returns_all_matches_when_no_limit():
    selected = select_articles(ARTICLES, "AI", None, None, None)

    assert [a["link"] for a in selected] == ["https://a.se/1", "https://c.se/3"]


def test_select_respects_limit():
    selected = select_articles(ARTICLES, "AI", None, None, 1)

    assert len(selected) == 1


def test_select_by_keyword_ignores_case():
    selected = select_articles(ARTICLES, None, "AGENT", None, None)

    assert len(selected) == 2


def test_select_by_rows_skips_missing_rows(capsys):
    selected = select_articles(ARTICLES, None, None, [1, 99], None)

    assert [a["link"] for a in selected] == ["https://b.se/2"]
    assert "99" in capsys.readouterr().out


def test_select_skips_articles_without_link():
    selected = select_articles(ARTICLES, None, None, [3], None)

    assert selected == []


# -------------------- prompt


def test_build_prompt_wraps_articles_and_marks_paywall():
    articles = [
        {"title": "Free", "source": "S1", "link": "https://a.se/1", "text": "Body"},
        {"title": "Paid", "source": "S2", "link": "https://b.se/2", "paywall": True},
    ]

    prompt = build_prompt(articles, fetch=True)

    assert prompt.count("<article") == 2
    assert prompt.count("</article>") == 2
    assert "Article text: Body" in prompt
    assert "Article text: not available (paywall)" in prompt


def test_build_prompt_without_fetch_has_no_article_text():
    articles = [{"title": "T", "source": "S", "link": "https://a.se/1"}]

    article_block = build_prompt(articles, fetch=False).split("<article", 1)[1]

    assert "Article text" not in article_block


# -------------------- review fixes


def test_sort_newest_first_handles_missing_and_naive_dates():
    articles = [
        {"link": "old", "published": "2026-10-14T08:00:00Z"},
        {"link": "missing", "published": ""},
        {"link": "new", "published": "2026-10-20T08:00:00Z"},
        {"link": "naive", "published": "2026-10-17T08:00:00"},
        {"link": "invalid", "published": "yesterday"},
    ]

    result = [a["link"] for a in sort_newest_first(articles)]

    assert result[:3] == ["new", "naive", "old"]
    assert set(result[3:]) == {"missing", "invalid"}


def test_select_without_filter_takes_newest_not_first_rows():
    articles = [
        {"link": "https://a.se/old", "published": "2026-10-14T08:00:00Z"},
        {"link": "https://a.se/new", "published": "2026-10-20T08:00:00Z"},
    ]

    selected = select_articles(articles, None, None, None, 1)

    assert selected[0]["link"] == "https://a.se/new"


def test_select_by_rows_keeps_given_order():
    articles = [
        {"link": "https://a.se/old", "published": "2026-10-14T08:00:00Z"},
        {"link": "https://a.se/new", "published": "2026-10-20T08:00:00Z"},
    ]

    selected = select_articles(articles, None, None, [0, 1], None)

    assert [a["link"] for a in selected] == ["https://a.se/old", "https://a.se/new"]


def test_dry_run_prints_prompt(tmp_path, monkeypatch, capsys):
    csv_path = tmp_path / "news.csv"
    csv_path.write_text(
        "title,link,source,published,subject,description\n"
        "Agent news,https://a.se/1,Source,2026-10-20T08:00:00Z,,A description\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "sys.argv", ["summarize_topic.py", "--csv", str(csv_path), "--dry-run"]
    )

    main()

    out = capsys.readouterr().out
    assert "--- Prompt ---" in out
    assert "Title: Agent news" in out
    assert "Dry run: no call to Claude made." in out
