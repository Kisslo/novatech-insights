"""Shared helpers for the Content scripts.

Used by summarize_topic.py and draft_article.py (and later the source check).
The scripts import this file with `from content_tools import ...` and are run
as before, e.g. `uv run python src/summarize_topic.py`.

Tests must also import `content_tools` (not `src.content_tools`), otherwise
Python loads this file twice and mocks may hit the wrong copy. pytest finds it
through `pythonpath = ["src"]` in pyproject.toml.

Contents:
- Command line: positive_int.
- Article fetching: robots.txt check, paywall detection, text extraction.
  Article text is kept in memory only and is never saved to disk.
- Claude: prices, cost estimate, the API call and a dry-run printout.
- Source links: compare links in a generated text with the links we sent.
"""

import argparse
import json
import os
import re
import sys
import threading
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

USER_AGENT = "NovatechInsights/0.1 (student project)"
FETCH_TIMEOUT_SECONDS = 20
FETCH_WORKERS = 5  # articles downloaded at the same time
MAX_DOWNLOAD_BYTES = 3_000_000  # stop reading very large pages
MAX_WORDS_PER_ARTICLE = 1200  # longer articles are cut to save tokens
MIN_WORDS_FOR_READABLE = 50  # less than this is not a usable article text
PHRASE_CHECK_MAX_WORDS = 150  # paywall phrases only count on short texts

# Phrases that paywalls show instead of the article (lowercase).
PAYWALL_PHRASES = (
    # English
    "subscribe to continue reading",
    "subscribe to read the full",
    "subscribe to keep reading",
    "to continue reading, subscribe",
    "this article is for subscribers",
    "this article is only available to subscribers",
    "already a subscriber",
    "become a member to read",
    "sign in to read the full",
    "unlock this article",
    "this content is for paid",
    "start your free trial to continue",
    # Swedish
    "logga in för att läsa",
    "bli prenumerant",
    "för prenumeranter",
    "endast för prenumeranter",
    "läs hela artikeln med",
    "lås upp artikeln",
    "redan prenumerant",
)

# Weaker words that also appear in menus of free sites. They only count when
# the page has almost no article text (below MIN_WORDS_FOR_READABLE).
PAYWALL_HINTS = ("premium", "paywall", "prenumerera", "subscribe", "plus-artikel")

JSON_LD_PATTERN = re.compile(
    r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.DOTALL | re.IGNORECASE,
)
META_TAG_PATTERN = re.compile(r"<meta\b[^>]*>", re.IGNORECASE)
META_ATTR_PATTERN = re.compile(r'([a-zA-Z:_-]+)\s*=\s*["\']([^"\']*)["\']')
LINK_PATTERN = re.compile(r"https?://[^\s)\]>\"']+")

# USD per million tokens (input, output). Check current prices before relying on them:
# https://platform.claude.com/docs/en/about-claude/models/overview
PRICES_PER_MTOK = {
    "claude-sonnet-5-5": (2.0, 10.0),
    "claude-opus-5-5": (4.0, 20.0),
}


# -------------------- command line


def positive_int(value: str) -> int:
    """argparse type: a whole number of at least 1."""
    try:
        number = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"'{value}' is not a whole number")
    if number < 1:
        raise argparse.ArgumentTypeError("must be 1 or more")
    return number


# -------------------- robots.txt

_robots_cache: dict[str, tuple[RobotFileParser | None, str]] = {}
_robots_lock = threading.Lock()


def _load_robots(robots_url: str) -> tuple[RobotFileParser | None, str]:
    """Download one robots.txt. Returns (parser or None if site is off-limits, reason)."""
    request = urllib.request.Request(robots_url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=FETCH_TIMEOUT_SECONDS) as resp:
            lines = resp.read().decode("utf-8", errors="replace").splitlines()
    except HTTPError as error:
        # RFC 9309: a missing robots.txt (4xx) means no rules apply,
        # but 401/403 or a server error (5xx) means we should stay away.
        if error.code in (401, 403) or error.code >= 500:
            return None, f"robots.txt answered {error.code}"
        empty = RobotFileParser()
        empty.parse([])
        return empty, "no robots.txt"
    except (URLError, OSError) as error:
        return None, f"could not read robots.txt ({error})"
    robots = RobotFileParser()
    robots.parse(lines)
    return robots, "allowed"


def allowed_by_robots(url: str) -> tuple[bool, str]:
    """Check the site's robots.txt before downloading an article.

    We download robots.txt ourselves with our own User-Agent. Python's
    RobotFileParser.read() uses "Python-urllib", which many news sites
    answer with 403, and it then treats the whole site as forbidden.
    Each site's robots.txt is downloaded only once per run.
    """
    parts = urlparse(url)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        return False, "not a web link"
    robots_url = f"{parts.scheme}://{parts.netloc}/robots.txt"
    with _robots_lock:
        cached = _robots_cache.get(robots_url)
    if cached is None:
        cached = _load_robots(robots_url)
        with _robots_lock:
            _robots_cache[robots_url] = cached
    robots, reason = cached
    if robots is None:
        return False, reason
    if robots.can_fetch(USER_AGENT, url):
        return True, reason
    return False, "disallowed by robots.txt"


# -------------------- paywall


def paywall_from_json_ld(html: str) -> bool | None:
    """Check schema.org markup for a paywall.

    Returns True if the page says it is not free, False if it says it is free,
    and None if the page gives no information.
    """
    found_free = False
    for block in JSON_LD_PATTERN.findall(html):
        try:
            data = json.loads(block)
        except json.JSONDecodeError:
            continue  # some sites have broken JSON-LD; skip it

        # JSON-LD can be one object, a list of objects, or an object with "@graph".
        items = data if isinstance(data, list) else [data]
        expanded = []
        for item in items:
            if isinstance(item, dict) and isinstance(item.get("@graph"), list):
                expanded.extend(item["@graph"])
            else:
                expanded.append(item)

        for item in expanded:
            if not isinstance(item, dict) or "isAccessibleForFree" not in item:
                continue
            # The value can be a bool (False) or a string ("False" / "false").
            if str(item["isAccessibleForFree"]).strip().lower() == "false":
                return True
            found_free = True

    return False if found_free else None


def paywall_from_meta(html: str) -> bool | None:
    """Check the article:content_tier meta tag (free / metered / locked).

    Returns True for metered or locked, False for free, None if missing.
    """
    for tag in META_TAG_PATTERN.findall(html):
        attrs = {k.lower(): v for k, v in META_ATTR_PATTERN.findall(tag)}
        key = attrs.get("property", attrs.get("name", "")).lower()
        if key == "article:content_tier":
            tier = attrs.get("content", "").strip().lower()
            if tier in ("locked", "metered"):
                return True
            if tier == "free":
                return False
    return None


def paywall_phrase(html: str) -> str | None:
    """Return the first known paywall phrase found in the page, or None."""
    lowered = html.lower()
    for phrase in PAYWALL_PHRASES:
        if phrase in lowered:
            return phrase
    return None


def detect_paywall(html: str, text: str | None) -> tuple[bool, str]:
    """Decide if a page is paywalled. Returns (is_paywalled, reason).

    The strongest signal decides. Markup that says the page is free stops
    the weaker checks, so a free article is not skipped because of a
    "subscribe" box in the page footer.
    """
    json_ld = paywall_from_json_ld(html)
    if json_ld:
        return True, "paywall (JSON-LD isAccessibleForFree=false)"
    meta = paywall_from_meta(html)
    if meta:
        return True, "paywall (content_tier)"
    if json_ld is False or meta is False:
        return False, "marked free"

    word_count = len(text.split()) if text else 0
    if word_count < PHRASE_CHECK_MAX_WORDS:
        phrase = paywall_phrase(html)
        if phrase:
            return True, f"paywall (phrase: '{phrase}')"
    if word_count < MIN_WORDS_FOR_READABLE:
        lowered = html.lower()
        for hint in PAYWALL_HINTS:
            if hint in lowered:
                return (
                    True,
                    f"paywall (likely: {word_count} words and '{hint}' on page)",
                )
    return False, "no paywall found"


# -------------------- fetching


def extract_article_text(html: str) -> str | None:
    """Return the main article text from a web page, without menus and ads."""
    import trafilatura  # only needed with --fetch

    return trafilatura.extract(
        html, include_comments=False, include_tables=False, favor_recall=True
    )


def shorten(text: str, max_words: int) -> str:
    """Cut a text to at most max_words words."""
    words = text.split()
    if len(words) <= max_words:
        return text
    return " ".join(words[:max_words]) + " …"


def download_html(url: str) -> tuple[str | None, str]:
    """Download a page. Returns (html or None, status message)."""
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=FETCH_TIMEOUT_SECONDS) as resp:
            content_type = resp.headers.get("Content-Type", "")
            if content_type and "html" not in content_type.lower():
                return None, f"not a web page ({content_type.split(';')[0]})"
            charset = resp.headers.get_content_charset() or "utf-8"
            raw = resp.read(MAX_DOWNLOAD_BYTES)
    except HTTPError as error:
        if error.code == 402:
            return None, "paywall (HTTP 402)"
        return None, f"download failed (HTTP {error.code})"
    except (URLError, OSError, ValueError) as error:
        return None, f"download failed ({error})"
    return raw.decode(charset, errors="replace"), "downloaded"


def fetch_article_text(url: str) -> tuple[str | None, str]:
    """Download one article. Returns (text or None, status message)."""
    allowed, reason = allowed_by_robots(url)
    if not allowed:
        return None, reason
    html, status = download_html(url)
    if html is None:
        return None, status

    text = extract_article_text(html)
    paywalled, reason = detect_paywall(html, text)
    if paywalled:
        return None, reason
    if not text:
        return None, "no article text found"
    word_count = len(text.split())
    if word_count < MIN_WORDS_FOR_READABLE:
        return None, f"only {word_count} words"
    return shorten(text, MAX_WORDS_PER_ARTICLE), f"{word_count} words"


def add_article_texts(articles: list[dict]) -> None:
    """Download several articles at the same time and attach their text.

    Each article needs a "link". The text is kept in memory only.
    Results print in the original order.
    """
    workers = min(FETCH_WORKERS, len(articles)) or 1
    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(lambda a: fetch_article_text(a["link"]), articles))
    for article, (text, status) in zip(articles, results):
        article["text"] = text
        article["paywall"] = status.startswith("paywall")
        label = "OK     " if text else ("PAYWALL" if article["paywall"] else "MISS   ")
        print(f"  {label} {article.get('source', '?')}: {status}")


# -------------------- source links


def check_source_links(
    text: str, articles: list[dict], required: list[dict] | None = None
) -> list[str]:
    """Compare links in a generated text with the links we sent. Returns warnings.

    Every link in the text must be one of `articles`. Every link in `required`
    (default: all `articles`) must appear in the text.
    """
    sent = {a["link"].rstrip("/") for a in articles}
    must_have = sent if required is None else {a["link"].rstrip("/") for a in required}
    found = {link.rstrip(".,;/") for link in LINK_PATTERN.findall(text)}
    found = {link.rstrip("/") for link in found}
    warnings = []
    for link in sorted(found - sent):
        warnings.append(f"Link not in the sources (check it!): {link}")
    for link in sorted(must_have - found):
        warnings.append(f"Source missing from 'Källor': {link}")
    return warnings


# -------------------- Claude


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float | None:
    """Cost in USD for a given number of tokens, or None if the price is unknown."""
    if model not in PRICES_PER_MTOK:
        return None
    price_in, price_out = PRICES_PER_MTOK[model]
    return (input_tokens * price_in + output_tokens * price_out) / 1_000_000


def format_cost(cost: float | None) -> str:
    """Show a cost as '$0.0140', or say that it is unknown."""
    if cost is None:
        return "unknown (model not in PRICES_PER_MTOK)"
    return f"${cost:.4f}"


def print_dry_run(
    model: str, system_prompt: str, prompt: str, max_output_tokens: int
) -> None:
    """Show both prompts and the highest possible cost, without calling Claude."""
    print("\n--- System prompt ---")
    print(system_prompt)
    print("\n--- Prompt ---")
    print(prompt)
    print("--- End of prompt ---\n")
    # Rough estimate: about 4 characters per token.
    est_input = (len(system_prompt) + len(prompt)) // 4
    max_cost = estimate_cost(model, est_input, max_output_tokens)
    print(f"Estimated input tokens: ~{est_input}")
    print(f"Max cost for this call: ~{format_cost(max_cost)}")
    print("Dry run: no call to Claude made.")


def call_claude(
    model: str, system_prompt: str, prompt: str, effort: str, max_tokens: int
) -> tuple[str, int, int]:
    """Send the prompt to Claude. Returns (text, input_tokens, output_tokens).

    max_tokens caps thinking plus answer; you only pay for what is used.
    Exits with a clear message if the API key is missing or the call fails.
    """
    import anthropic  # imported here so --dry-run works without the API

    if not os.getenv("ANTHROPIC_API_KEY"):
        sys.exit("ANTHROPIC_API_KEY is missing. Add it to your .env file.")

    client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from the environment
    try:
        response = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system_prompt,
            messages=[{"role": "user", "content": prompt}],
            output_config={"effort": effort},
        )
    except anthropic.AuthenticationError:
        sys.exit("The API key was rejected. Check ANTHROPIC_API_KEY in .env.")
    except anthropic.RateLimitError:
        sys.exit("Rate limit reached. Wait a minute and try again.")
    except anthropic.APIConnectionError:
        sys.exit("Could not reach the Claude API. Check your internet connection.")
    except anthropic.APIStatusError as error:
        sys.exit(f"Claude API error {error.status_code}: {error.message}")

    if response.stop_reason == "max_tokens":
        print("Warning: the answer was cut off (max_tokens reached).")
    details = getattr(response.usage, "output_tokens_details", None)
    thinking = getattr(details, "thinking_tokens", 0) or 0
    if thinking:
        print(f"Thinking tokens: {thinking} (included in output tokens)")
    text = "".join(b.text for b in response.content if b.type == "text").strip()
    return text, response.usage.input_tokens, response.usage.output_tokens
