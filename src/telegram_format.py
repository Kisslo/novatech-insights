"""Turn one labelled topic into a Telegram message with two buttons (issue #42).

Pure functions only: no network, no FastAPI, no Supabase. The API is a thin
wrapper around format_topic(), and the same function can be reused later
(for example to store the text in Supabase or to let n8n send it).

The text uses Telegram's HTML parse mode. Telegram only understands a few
tags (<b>, <a href>, ...), so &, < and > must be escaped everywhere else.
Limits from the Telegram Bot API:
- a message text is at most 4096 characters
- callback_data on a button is at most 64 bytes

Input (one topic, same fields as label_topics.normalize_topic() plus labels):
    {"id": 101, "label": "...", "why_relevant_sv": "...", "llm_relevance": 4,
     "article_count": 7, "source_count": 4, "counts_from_articles": False,
     "articles": [{"title": "...", "source": "...", "link": "https://..."}]}
"""

from urllib.parse import urlparse

MAX_MESSAGE_CHARS = 4096
MAX_CALLBACK_BYTES = 64
MAX_LABEL_CHARS = 200
MAX_WHY_CHARS = 800
MAX_TITLE_CHARS = 200
MAX_SOURCE_CHARS = 80
WRITE_PREFIX = "write"
SKIP_PREFIX = "skip"
WRITE_TEXT = "Skriv"
SKIP_TEXT = "Skippa"


def escape_html(text: str) -> str:
    """Escape &, < and > so Telegram shows them as text, not as tags.

    & is replaced first, otherwise the & in &lt; would be escaped again.
    """
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def escape_attribute(text: str) -> str:
    """Escape a value inside href="..." (also the double quote)."""
    return escape_html(text).replace('"', "&quot;")


def shorten(text: str, limit: int) -> str:
    """Collapse whitespace and cut long text with an ellipsis (…)."""
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def is_web_link(link: str) -> bool:
    """True for http(s) links. Other links (javascript:, ftp:, ...) are not
    made clickable."""
    parsed = urlparse(link)
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


def callback_data(prefix: str, topic_id: int) -> str:
    """Button payload, e.g. "write:101". Checked against Telegram's 64-byte limit."""
    data = f"{prefix}:{topic_id}"
    if len(data.encode("utf-8")) > MAX_CALLBACK_BYTES:
        raise ValueError(f"callback_data is longer than 64 bytes: {data}")
    return data


def check_labels(topic: dict) -> None:
    """Raise ValueError if the topic has not been labelled with label_topics.py."""
    for field in ("label", "why_relevant_sv"):
        value = topic.get(field)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"topic {topic.get('id')} has no {field}")
    relevance = topic.get("llm_relevance")
    # bool is a subclass of int in Python, so True would otherwise pass as 1
    if isinstance(relevance, bool) or not isinstance(relevance, int):
        raise ValueError(f"topic {topic.get('id')} has no llm_relevance")
    if not 1 <= relevance <= 5:
        raise ValueError(f"topic {topic.get('id')} has llm_relevance {relevance}")


def format_text(topic: dict, rank: int) -> str:
    """Telegram HTML text: rank + headline, why it matters, counts, top links.

    Text is shortened first and escaped afterwards, so an escape sequence
    such as &amp; is never cut in half.
    """
    prefix = "minst " if topic.get("counts_from_articles") else ""
    lines = [
        f"<b>{rank}. {escape_html(shorten(topic['label'], MAX_LABEL_CHARS))}</b>",
        "",
        escape_html(shorten(topic["why_relevant_sv"], MAX_WHY_CHARS)),
        "",
        f"Källor: {prefix}{topic['source_count']}"
        f" · Artiklar: {prefix}{topic['article_count']}"
        f" · AI-relevans: {topic['llm_relevance']}/5",
        "",
    ]
    for article in topic["articles"]:
        title = escape_html(shorten(article["title"], MAX_TITLE_CHARS))
        source = escape_html(shorten(article["source"], MAX_SOURCE_CHARS))
        if is_web_link(article["link"]):
            href = escape_attribute(article["link"])
            lines.append(f'• <a href="{href}">{title}</a> – {source}')
        else:
            lines.append(f"• {title} – {source}")
    text = "\n".join(lines)
    if len(text) > MAX_MESSAGE_CHARS:
        raise ValueError(f"message for topic {topic['id']} is too long")
    return text


def format_topic(topic: dict, rank: int) -> dict:
    """One labelled topic -> one ready-to-send Telegram message.

    Raises ValueError if the topic is not labelled or the message would
    break a Telegram limit. The caller skips and reports such topics.
    """
    check_labels(topic)
    buttons = [
        {"text": WRITE_TEXT, "callback_data": callback_data(WRITE_PREFIX, topic["id"])},
        {"text": SKIP_TEXT, "callback_data": callback_data(SKIP_PREFIX, topic["id"])},
    ]
    return {
        "topic_id": topic["id"],
        "rank": rank,
        "text": format_text(topic, rank),
        "parse_mode": "HTML",
        "buttons": buttons,
    }
