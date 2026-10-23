import pytest

from content_tools import (
    check_source_links,
    detect_paywall,
    estimate_cost,
    format_cost,
    paywall_from_json_ld,
    paywall_from_meta,
)


def json_ld(content):
    return f'<script type="application/ld+json">{content}</script>'


# -------------------- JSON-LD


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


# -------------------- meta tag


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


# -------------------- decision


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


# -------------------- source links


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

def test_check_source_links_only_requires_given_sources():
    articles = [{"link": "https://a.se/1"}, {"link": "https://b.se/2"}]
    text = "Källor\n- https://a.se/1"

    assert check_source_links(text, articles, required=articles[:1]) == []
    assert check_source_links(text + "\n- https://x.se/9", articles, []) == [
        "Link not in the sources (check it!): https://x.se/9"
    ]


# -------------------- cost


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
