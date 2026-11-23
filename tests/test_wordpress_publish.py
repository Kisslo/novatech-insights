"""Tests for src/wordpress_publish.py (issue #81). WordPress is never called."""

import base64
import io
import json
from urllib.error import HTTPError, URLError

import pytest

import wordpress_publish as wp
from wordpress_publish import (
    WordPressConfigError,
    WordPressError,
    WordPressSettings,
    article_to_html,
    build_payload,
    check_publishable,
    create_post,
    inline_html,
    split_headline,
    wordpress_settings,
)

PASSWORD = "abcd efgh ijkl mnop qrst uvwx"
SETTINGS = WordPressSettings("https://example.com", "bot", PASSWORD)

ARTICLE = "\n".join(
    [
        "# AI-regler: **börja** nu",
        "",
        "Ingressen säger det viktigaste <först> & sen resten.",
        "En andra rad i samma stycke.",
        "",
        "## Vad säger källorna",
        "",
        "Enligt [EU](https://example.com/eu) gäller nya regler.",
        "",
        "## Källor",
        "- Example Tech News: EU guidance – https://example.com/tech/eu-guidance",
        "- Exempel Affärer: Nya regler – https://example.com/affarer/regler",
    ]
)
LINKEDIN = "Första meningen. Andra meningen. Läs mer: [LÄNK]"


@pytest.fixture
def wp_env(monkeypatch):
    monkeypatch.setenv("WORDPRESS_URL", "https://example.com/")
    monkeypatch.setenv("WORDPRESS_USER", "bot")
    monkeypatch.setenv("WORDPRESS_APP_PASSWORD", PASSWORD)
    monkeypatch.delenv("WORDPRESS_POST_STATUS", raising=False)
    monkeypatch.delenv("WORDPRESS_CATEGORY_ID", raising=False)


# -------------------- settings


def test_settings_defaults_to_draft_without_category(wp_env):
    settings = wordpress_settings()
    assert settings.url == "https://example.com"
    assert settings.post_status == "draft"
    assert settings.category_id is None


def test_settings_password_not_in_repr(wp_env):
    assert PASSWORD not in repr(wordpress_settings())


def test_settings_reads_status_and_category(wp_env, monkeypatch):
    monkeypatch.setenv("WORDPRESS_POST_STATUS", "publish")
    monkeypatch.setenv("WORDPRESS_CATEGORY_ID", "7")
    settings = wordpress_settings()
    assert settings.post_status == "publish"
    assert settings.category_id == 7


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("WORDPRESS_APP_PASSWORD", ""),
        ("WORDPRESS_URL", "http://example.com"),
        ("WORDPRESS_URL", "ftp://example.com"),
        ("WORDPRESS_POST_STATUS", "private"),
        ("WORDPRESS_CATEGORY_ID", "abc"),
        ("WORDPRESS_CATEGORY_ID", "0"),
    ],
)
def test_settings_refuses_invalid_values(wp_env, monkeypatch, name, value):
    monkeypatch.setenv(name, value)
    with pytest.raises(WordPressConfigError) as error:
        wordpress_settings()
    assert PASSWORD not in str(error.value)


def test_settings_allows_http_for_localhost(wp_env, monkeypatch):
    monkeypatch.setenv("WORDPRESS_URL", "http://localhost:8080")
    assert wordpress_settings().url == "http://localhost:8080"


# -------------------- checks


def test_clean_draft_is_publishable():
    assert check_publishable(ARTICLE, LINKEDIN) == []


def test_unverified_tags_block_publishing():
    problems = check_publishable(
        ARTICLE + "\nEn siffra [UNVERIFIED].", "Text [UNVERIFIED]. Läs mer: [LÄNK]"
    )
    assert problems == ["2 [UNVERIFIED] tag(s) left in the texts."]


def test_placeholders_block_publishing():
    problems = check_publishable(ARTICLE + "\nSkrivet av [NAMN]. [LÄNK]", LINKEDIN)
    assert problems == ["Placeholder(s) in the article: [LÄNK], [NAMN]."]


def test_link_placeholder_is_allowed_in_linkedin_only():
    assert check_publishable(ARTICLE, "Hej [FÖRETAG]. Läs mer: [LÄNK]") == [
        "Placeholder(s) in the LinkedIn post: [FÖRETAG]."
    ]


def test_markdown_link_text_is_not_a_placeholder():
    assert (
        check_publishable(ARTICLE + "\nSe [EU](https://example.com/x).", LINKEDIN) == []
    )


def test_article_without_headline_is_refused():
    assert "The article has no '# ' headline." in check_publishable("Bara text.", "")


# -------------------- HTML


def test_split_headline_removes_bold_and_headline_line():
    title, body = split_headline(ARTICLE)
    assert title == "AI-regler: börja nu"
    assert not body.startswith("#")


def test_html_escapes_text_and_joins_paragraph_lines():
    html = article_to_html(split_headline(ARTICLE)[1])
    assert (
        "<p>Ingressen säger det viktigaste &lt;först&gt; &amp; sen resten. "
        "En andra rad i samma stycke.</p>"
    ) in html
    assert "<först>" not in html


def test_html_headings_links_and_source_list():
    html = article_to_html(split_headline(ARTICLE)[1])
    assert "<h2>Vad säger källorna</h2>" in html
    assert (
        '<p>Enligt <a href="https://example.com/eu">EU</a> gäller nya regler.</p>'
        in html
    )
    assert "<h2>Källor</h2>\n<ul>\n<li>Example Tech News: EU guidance – " in html
    assert '<a href="https://example.com/affarer/regler">' in html
    assert html.count("<li>") == 2


def test_bare_link_keeps_sentence_dot_outside():
    assert inline_html("Läs https://example.com/a.") == (
        'Läs <a href="https://example.com/a">https://example.com/a</a>.'
    )


def test_unsafe_links_and_tags_are_never_html():
    html = inline_html('[klick](javascript:alert(1)) <script>x</script> "citat"')
    assert "<a" not in html
    assert "<script>" not in html
    assert "&quot;citat&quot;" in html


def test_bold_becomes_strong():
    assert inline_html("Det **viktiga** först") == "Det <strong>viktiga</strong> först"


def test_payload_has_only_article_and_settings():
    settings = WordPressSettings("https://example.com", "bot", PASSWORD, "draft", 7)
    payload = build_payload(ARTICLE, settings)
    assert set(payload) == {"title", "content", "status", "categories"}
    assert payload["title"] == "AI-regler: börja nu"
    assert payload["status"] == "draft"
    assert payload["categories"] == [7]
    assert "AI-regler" not in payload["content"]


def test_payload_without_category():
    assert "categories" not in build_payload(ARTICLE, SETTINGS)


# -------------------- create_post


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def http_error(code, body):
    return HTTPError(
        "https://example.com/wp-json/wp/v2/posts",
        code,
        "error",
        {},
        io.BytesIO(json.dumps(body).encode("utf-8")),
    )


def test_create_post_sends_auth_and_payload(monkeypatch):
    seen = {}

    def fake_urlopen(request, timeout):
        seen["url"] = request.full_url
        seen["auth"] = request.get_header("Authorization")
        seen["body"] = json.loads(request.data)
        seen["timeout"] = timeout
        answer = {"id": 42, "link": "https://example.com/?p=42", "status": "draft"}
        return FakeResponse(json.dumps(answer).encode("utf-8"))

    monkeypatch.setattr(wp, "urlopen", fake_urlopen)
    result = create_post(SETTINGS, {"title": "T", "content": "<p>x</p>"})

    assert result == {"id": 42, "link": "https://example.com/?p=42", "status": "draft"}
    assert seen["url"] == "https://example.com/wp-json/wp/v2/posts"
    token = base64.b64decode(seen["auth"].removeprefix("Basic ")).decode("utf-8")
    assert token == f"bot:{PASSWORD}"
    assert seen["body"] == {"title": "T", "content": "<p>x</p>"}
    assert seen["timeout"] == wp.WORDPRESS_TIMEOUT_SECONDS


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (
            http_error(401, {"code": "rest_not_logged_in"}),
            "HTTP 401 rest_not_logged_in",
        ),
        (http_error(500, {"code": "internal"}), "HTTP 500 internal"),
        (URLError("timed out"), "Could not reach WordPress"),
    ],
)
def test_create_post_errors_never_contain_password(monkeypatch, error, expected):
    def fake_urlopen(request, timeout):
        raise error

    monkeypatch.setattr(wp, "urlopen", fake_urlopen)
    with pytest.raises(WordPressError) as raised:
        create_post(SETTINGS, {})
    assert expected in str(raised.value)
    assert PASSWORD not in str(raised.value)
    assert raised.value.__cause__ is None


def test_create_post_refuses_answer_without_id(monkeypatch):
    monkeypatch.setattr(
        wp, "urlopen", lambda request, timeout: FakeResponse(b'{"link": "x"}')
    )
    with pytest.raises(WordPressError, match="no post id"):
        create_post(SETTINGS, {})
