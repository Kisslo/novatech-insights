"""Turn an approved article draft into a WordPress post (issue #81).

Used by the endpoint POST /drafts/{post_id}/publish:
    problems = check_publishable(article, linkedin)   # 409 if not empty
    settings = wordpress_settings()                   # from .env
    payload = build_payload(article, settings)        # title, HTML, status
    post = create_post(settings, payload)             # {"id", "link", "status"}

The article is Markdown from draft_article.py: a "# " headline, paragraphs,
"## " sections and a "## Källor" list with one "- <publication>: <title> –
<link>" line per source. Only the article is sent. The reviewer notes are
never part of the payload.

The Markdown is turned into HTML here instead of with a library: the subset
is small, and every piece of text is escaped, so nothing in a draft can
become a tag on the website. Only plain http(s) links become <a> tags.

Settings in .env:
    WORDPRESS_URL            for example https://novatech-solutions.se
                             (http is only allowed for localhost)
    WORDPRESS_USER           the WordPress user that writes the posts
    WORDPRESS_APP_PASSWORD   an application password for that user, never
                             the login password. Never logged or returned.
    WORDPRESS_POST_STATUS    draft (default) or publish
    WORDPRESS_CATEGORY_ID    optional category id; empty = WordPress default
"""

import base64
import json
import os
import re
import socket
from dataclasses import dataclass, field
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from draft_article import LINK_PLACEHOLDER, UNVERIFIED_TAG

POST_STATUSES = ("draft", "publish")
DEFAULT_POST_STATUS = "draft"
WORDPRESS_TIMEOUT_SECONDS = 30
POSTS_PATH = "/wp-json/wp/v2/posts"
LOCAL_HOSTS = ("localhost", "127.0.0.1", "::1")

# Placeholders such as [LÄNK] or [NAMN]: capital letters in brackets that are
# not the text of a Markdown link "[EU](https://...)".
PLACEHOLDER_PATTERN = re.compile(r"\[[A-ZÅÄÖ][A-ZÅÄÖ0-9 _-]*\](?!\()")
# A Markdown link [text](https://...) or a bare https://... link.
INLINE_LINK_PATTERN = re.compile(
    r"\[([^\]\n]+)\]\((https?://[^\s<>\"'()]+)\)|(https?://[^\s<>\"'\[\]()]+)"
)
BOLD_PATTERN = re.compile(r"\*\*(.+?)\*\*")
# "1. text" or "1) text": an item in a numbered list.
NUMBERED_ITEM_PATTERN = re.compile(r"\d{1,2}[.)] ")
TRAILING_PUNCTUATION = ".,;:!?"


class WordPressError(Exception):
    """WordPress could not be reached or refused the post.

    The message is written for the server log. It never contains the password.
    not_created is True when WordPress surely did not save the post (it
    answered with a 4xx error, or could not be reached at all). Then the
    publishing can safely be tried again. After a timeout or a 5xx answer
    the post may exist, so not_created is False.
    """

    def __init__(self, message: str, *, not_created: bool = False) -> None:
        super().__init__(message)
        self.not_created = not_created


class WordPressConfigError(WordPressError):
    """A WORDPRESS_* setting in .env is missing or invalid."""


@dataclass(frozen=True)
class WordPressSettings:
    url: str
    user: str
    # repr=False: the password is never shown if the settings are printed.
    app_password: str = field(repr=False)
    post_status: str = DEFAULT_POST_STATUS
    category_id: int | None = None


# -------------------- settings


def wordpress_settings() -> WordPressSettings:
    """Read the WORDPRESS_* settings. Raises WordPressConfigError if invalid."""
    url = os.getenv("WORDPRESS_URL", "").strip().rstrip("/")
    user = os.getenv("WORDPRESS_USER", "").strip()
    app_password = os.getenv("WORDPRESS_APP_PASSWORD", "").strip()
    if not url or not user or not app_password:
        raise WordPressConfigError(
            "WORDPRESS_URL, WORDPRESS_USER and WORDPRESS_APP_PASSWORD must be set."
        )
    parts = urlsplit(url)
    local = parts.hostname in LOCAL_HOSTS
    if parts.scheme != "https" and not (parts.scheme == "http" and local):
        # The password is sent with every call, so only over https
        # (plain http only for a test site on this computer).
        raise WordPressConfigError("WORDPRESS_URL must start with https://.")

    post_status = os.getenv("WORDPRESS_POST_STATUS", "").strip() or DEFAULT_POST_STATUS
    if post_status not in POST_STATUSES:
        raise WordPressConfigError(
            f"WORDPRESS_POST_STATUS must be draft or publish, not '{post_status}'."
        )

    raw_category = os.getenv("WORDPRESS_CATEGORY_ID", "").strip()
    category_id = None
    if raw_category:
        if not raw_category.isdigit() or int(raw_category) < 1:
            raise WordPressConfigError(
                "WORDPRESS_CATEGORY_ID must be a positive whole number."
            )
        category_id = int(raw_category)
    return WordPressSettings(url, user, app_password, post_status, category_id)


# -------------------- checks


def check_publishable(article: str, linkedin: str) -> list[str]:
    """Reasons why the draft cannot be published yet. Empty list = ok.

    Kisslo fixes these with Ändra. [LÄNK] is allowed in the LinkedIn post:
    it is replaced with the article's link after publishing.
    """
    problems = []
    title, body = split_headline(article)
    if not title:
        problems.append("The article has no '# ' headline.")
    if not body.strip():
        problems.append("The article has no text under the headline.")

    unverified = article.count(UNVERIFIED_TAG) + linkedin.count(UNVERIFIED_TAG)
    if unverified:
        problems.append(f"{unverified} {UNVERIFIED_TAG} tag(s) left in the texts.")

    in_article = sorted(set(PLACEHOLDER_PATTERN.findall(article)) - {UNVERIFIED_TAG})
    in_linkedin = sorted(
        set(PLACEHOLDER_PATTERN.findall(linkedin)) - {UNVERIFIED_TAG, LINK_PLACEHOLDER}
    )
    if in_article:
        problems.append(f"Placeholder(s) in the article: {', '.join(in_article)}.")
    if in_linkedin:
        problems.append(
            f"Placeholder(s) in the LinkedIn post: {', '.join(in_linkedin)}."
        )
    return problems


# -------------------- Markdown to HTML


def escape_html(text: str) -> str:
    """Escape &, <, > and quotes so the text is shown as text on the website."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def split_headline(article: str) -> tuple[str, str]:
    """Return (headline, rest). The headline is the first "# " line."""
    lines = article.strip().splitlines()
    for index, line in enumerate(lines):
        if line.startswith("# "):
            title = BOLD_PATTERN.sub(r"\1", line[2:]).strip()
            return title, "\n".join(lines[:index] + lines[index + 1 :]).strip()
    return "", article.strip()


def text_html(text: str) -> str:
    """Escaped text with **bold** as <strong>."""
    return BOLD_PATTERN.sub(r"<strong>\1</strong>", escape_html(text))


def inline_html(text: str) -> str:
    """One line of Markdown as HTML: escaped text, **bold** and http(s) links."""
    pieces, position = [], 0
    for match in INLINE_LINK_PATTERN.finditer(text):
        pieces.append(text_html(text[position : match.start()]))
        label, url, bare = match.groups()
        after = ""
        if bare:
            # "…läs https://example.com/a." – the dot ends the sentence.
            url = bare.rstrip(TRAILING_PUNCTUATION)
            after = bare[len(url) :]
            label = url
        pieces.append(f'<a href="{escape_html(url)}">{escape_html(label)}</a>')
        pieces.append(escape_html(after))
        position = match.end()
    pieces.append(text_html(text[position:]))
    return "".join(pieces)


def article_to_html(body: str) -> str:
    """The article body (without the headline) as WordPress HTML.

    "## " and "### " become <h2> and <h3>, lines starting with "- " or "* "
    become a bulleted list, lines starting with "1. " (any number) become a
    numbered list, and other lines become paragraphs (lines in the same
    paragraph are joined). A blank line ends a paragraph or a list.
    """
    html, paragraph, items = [], [], []
    list_tag = ""  # "ul" or "ol" while items are collected

    def flush() -> None:
        nonlocal list_tag
        if paragraph:
            html.append(f"<p>{' '.join(paragraph)}</p>")
            paragraph.clear()
        if items:
            rows = "\n".join(f"<li>{item}</li>" for item in items)
            html.append(f"<{list_tag}>\n{rows}\n</{list_tag}>")
            items.clear()
        list_tag = ""

    def add_item(tag: str, text: str) -> None:
        nonlocal list_tag
        if paragraph or (items and list_tag != tag):
            flush()
        list_tag = tag
        items.append(inline_html(text.strip()))

    for raw in body.splitlines():
        line = raw.strip()
        numbered = NUMBERED_ITEM_PATTERN.match(line)
        if not line:
            flush()
        elif line.startswith("### "):
            flush()
            html.append(f"<h3>{inline_html(line[4:].strip())}</h3>")
        elif line.startswith("## "):
            flush()
            html.append(f"<h2>{inline_html(line[3:].strip())}</h2>")
        elif line.startswith(("- ", "* ")):
            add_item("ul", line[2:])
        elif numbered:
            add_item("ol", line[numbered.end() :])
        else:
            if items:
                flush()
            paragraph.append(inline_html(line))
    flush()
    return "\n".join(html)


def build_payload(article: str, settings: WordPressSettings) -> dict:
    """The JSON body for POST /wp-json/wp/v2/posts. Only the article is used."""
    title, body = split_headline(article)
    payload = {
        "title": escape_html(title),
        "content": article_to_html(body),
        "status": settings.post_status,
    }
    if settings.category_id is not None:
        payload["categories"] = [settings.category_id]
    return payload


# -------------------- WordPress REST API


def auth_header(settings: WordPressSettings) -> str:
    """Basic auth with the application password (WordPress REST API)."""
    token = f"{settings.user}:{settings.app_password}".encode("utf-8")
    return "Basic " + base64.b64encode(token).decode("ascii")


def edit_link(settings: WordPressSettings, wordpress_post_id: int) -> str:
    """The admin page where Kisslo can look at and publish a draft."""
    return f"{settings.url}/wp-admin/post.php?post={wordpress_post_id}&action=edit"


def wordpress_message(error: HTTPError) -> str:
    """WordPress's error "code" (for example rest_cannot_create), or ""."""
    try:
        body = json.loads(error.read().decode("utf-8"))
    except OSError, ValueError:
        return ""
    code = body.get("code") if isinstance(body, dict) else None
    return code[:100] if isinstance(code, str) else ""


def create_post(settings: WordPressSettings, payload: dict) -> dict:
    """Create the post. Returns {"id", "link", "status"} from WordPress.

    Raises WordPressError on any failure. Note: if the answer is lost after
    WordPress saved the post (for example a timeout), the post may exist
    anyway. The endpoint handles that with the publish_requested status.
    """
    request = Request(
        settings.url + POSTS_PATH,
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={
            "Authorization": auth_header(settings),
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    try:
        with urlopen(request, timeout=WORDPRESS_TIMEOUT_SECONDS) as response:
            data = json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        code = wordpress_message(error)
        refused = error.code < 500
        if error.code in (401, 403):
            raise WordPressError(
                f"WordPress refused the post (HTTP {error.code} {code}). "
                "Check WORDPRESS_USER, the application password and the user's role.",
                not_created=True,
            ) from None
        raise WordPressError(
            f"WordPress answered HTTP {error.code} {code}.", not_created=refused
        ) from None
    except (URLError, OSError) as error:
        reason = getattr(error, "reason", error)
        # No connection at all (refused, unknown host): nothing was sent.
        unreachable = isinstance(reason, (ConnectionRefusedError, socket.gaierror))
        raise WordPressError(
            f"Could not reach WordPress ({error}).", not_created=unreachable
        ) from None
    except ValueError:
        raise WordPressError("WordPress did not answer with JSON.") from None

    if (
        not isinstance(data, dict)
        or not isinstance(data.get("id"), int)
        or not isinstance(data.get("link"), str)
    ):
        raise WordPressError("Unexpected answer from WordPress: no post id or link.")
    return {"id": data["id"], "link": data["link"], "status": data.get("status")}
