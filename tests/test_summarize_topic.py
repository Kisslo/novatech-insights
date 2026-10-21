import pytest

from src.summarize_topic import (
    build_prompt,
    check_source_links,
    detect_paywall,
    estimate_cost,
    format_cost,
    main,
    parse_rows,
    paywall_from_json_ld,
    paywall_from_meta,
    select_articles,
    sort_newest_first,
)


def json_ld(content):
    return f'<script type="application/ld+json">{content}</script>'


# ---------------------------------------------------------------- JSON-LD


@pytest.mark.parametrize(
    "content",
    [
        '{"isAccessibleForFree": false}',
        '{"isAccessibleForFree": "False"}',
        '[{"@type": "WebPage"}, {"isAccessibleForFree": "false"}]',
        '{"@graph": [{"@type": "WebPage"}, {"isAccessibleForFree": false}]}',
    ],
)
def test_json_ld_detects_paywall(content):
    assert paywall_from_json_ld(json_ld(content)) is True


def test_json_ld_marked_free_returns_false():
    assert paywall_from_json_ld(json_ld('{"isAccessibleForFree": true}')) is False


@pytest.mark.parametrize(
    "html",
    [
        "<p>No structured data here</p>",
        json_ld("{broken json"),
        json_ld('{"@type": "NewsArticle"}'),
    ],
)
def test_json_ld_without_information_returns_none(html):
    assert paywall_from_json_ld(html) is None


def test_json_ld_paywall_wins_over_free_block():
    html = json_ld('{"isAccessibleForFree": true}') + json_ld(
        '{"isAccessibleForFree": false}'
    )

    assert paywall_from_json_ld(html) is True


# ---------------------------------------------------------------- meta tag


@pytest.mark.parametrize(
    ("html", "expected"),
    [
        ('<meta property="article:content_tier" content="locked">', True),
        ('<meta property="article:content_tier" content="metered">', True),
        ("<meta content='free' name='article:content_tier' />", False),
        ('<meta name="description" content="locked">', None),
        ("<p>No meta tags</p>", None),
    ],
)
def test_paywall_from_meta(html, expected):
    assert paywall_from_meta(html) is expected


# ---------------------------------------------------------------- decision


def test_detect_paywall_from_json_ld():
    html = json_ld('{"isAccessibleForFree": false}')

    is_paywalled, reason = detect_paywall(html, "word " * 500)

    assert is_paywalled
    assert "JSON-LD" in reason


def test_detect_paywall_short_teaser_with_phrase():
    html = "<div>Subscribe to continue reading</div>"

    is_paywalled, reason = detect_paywall(html, "teaser " * 100)

    assert is_paywalled
    assert "phrase" in reason


def test_detect_paywall_ignores_phrase_in_long_article():
    # Ars Technica case: a subscription box on a page with a readable article.
    html = "<footer>Already a subscriber? Log in</footer>"

    is_paywalled, _ = detect_paywall(html, "word " * 287)

    assert not is_paywalled


def test_detect_paywall_almost_empty_page_with_hint():
    # Breakit case: only the menu was extracted and the page mentions premium.
    html = '<nav>Logga in Prenumerera</nav><div class="premium"></div>'

    is_paywalled, reason = detect_paywall(html, "Nyheter Rapporter Logga in " * 5)

    assert is_paywalled
    assert "likely" in reason


def test_detect_paywall_hint_ignored_when_text_is_readable():
    html = "<nav>Prenumerera</nav>"

    is_paywalled, _ = detect_paywall(html, "word " * 80)

    assert not is_paywalled


def test_detect_paywall_marked_free_stops_weaker_checks():
    html = json_ld('{"isAccessibleForFree": true}') + "Bli prenumerant"

    is_paywalled, reason = detect_paywall(html, "short")

    assert not is_paywalled
    assert reason == "marked free"


def test_detect_paywall_handles_missing_text():
    is_paywalled, _ = detect_paywall("<p>Nothing</p>", None)

    assert not is_paywalled


# ---------------------------------------------------------------- rows


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


# ---------------------------------------------------------------- selection

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


# ---------------------------------------------------------------- prompt


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


# ---------------------------------------------------------------- source links


def test_check_source_links_all_correct():
    articles = [{"link": "https://a.se/1"}, {"link": "https://b.se/2/"}]
    summary = "Källor\n- https://a.se/1\n- https://b.se/2"

    assert check_source_links(summary, articles) == []


def test_check_source_links_finds_invented_and_missing_links():
    articles = [{"link": "https://a.se/1"}, {"link": "https://b.se/2"}]
    summary = "Källor\n- https://a.se/1\n- https://invented.com/x."

    warnings = check_source_links(summary, articles)

    assert any("invented.com/x" in w and "not in the sources" in w for w in warnings)
    assert any("b.se/2" in w and "missing" in w for w in warnings)


# ---------------------------------------------------------------- review fixes


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


def test_estimate_cost_unknown_model_is_none():
    assert estimate_cost("unknown-model", 1000, 1000) is None


def test_estimate_cost_known_model():
    assert estimate_cost("claude-sonnet-5-5", 1_000_000, 0) == 2.0


@pytest.mark.parametrize(
    ("cost", "expected"),
    [(0.014, "$0.0140"), (0.0, "$0.0000"), (None, "unknown")],
)
def test_format_cost(cost, expected):
    assert format_cost(cost).startswith(expected)


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
