"""Endpoint for n8n: publish an approved draft to WordPress (issue #81).

    POST /drafts/{post_id}/publish            with header X-API-Key
    POST /drafts/{post_id}/publish?dry_run=true
    JSON body: {"version": <n>}  (the version in publish:<post_id>:<n>)

n8n calls it when Kisslo presses Publicera under a draft in Telegram. The
router is added to the app in telegram_api.py, which also adds the API key
check. What one call does:
1. Checks before anything is sent: the post exists, its status is
   draft_generated, the version is the latest draft, and the article has
   no [UNVERIFIED] tags or placeholders (wordpress_publish.check_publishable).
2. Locks the version: status publish_requested (publish_store.py).
3. Creates the post in WordPress through the REST API. The status comes
   from WORDPRESS_POST_STATUS, draft by default.
4. Saves the result: status published, WordPress post id, URL and time.
5. Returns Telegram messages: the article link and the LinkedIn post with
   [LÄNK] replaced by the URL, for Kisslo to post himself.

Only the article is sent to WordPress; the reviewer notes are never read.
A second call after success answers 409 and creates no new post. If
WordPress surely did not create the post (it refused, or could not be
reached), the status goes back to draft_generated, so Kisslo can try again.
If the answer was lost (a timeout), the status stays publish_requested and
a new call answers 409 until someone has checked WordPress.

Answers:
    200  published (or dry run)
    401  wrong or missing API key
    404  no such post
    409  wrong status, old version, [UNVERIFIED] or a placeholder left,
         already published or publishing in progress
    422  invalid body, for example a missing version
    500  WORDPRESS_* or TELEGRAM_SOURCE settings missing or invalid
    502  WordPress or Supabase failed
"""

import logging
import os
import threading

from fastapi import APIRouter, HTTPException, Path, Query
from pydantic import BaseModel, ConfigDict, Field

from draft_api import MAX_HEADLINE_CHARS, split_into_parts
from draft_article import LINK_PLACEHOLDER
from draft_store import SOURCES, PostNotFound, PostNotReady, StoreError
from publish_store import (
    PUBLISH_FROM,
    PUBLISHED_STATUS,
    REQUESTED_STATUS,
    cancel_publish_request,
    load_latest_draft,
    load_publication,
    mark_published,
    request_publish,
)
from telegram_format import (
    escape_attribute,
    escape_html,
    is_web_link,
    shorten,
)
from wordpress_publish import (
    WordPressConfigError,
    WordPressError,
    build_payload,
    check_publishable,
    create_post,
    edit_link,
    split_headline,
    wordpress_settings,
)

logger = logging.getLogger("publish_api")
router = APIRouter()

# Posts being published right now. A second request for the same post (a
# double click) is refused. With supabase, request_publish also refuses it
# in the database; this lock covers the fixture source.
_in_progress: set[int] = set()
_in_progress_lock = threading.Lock()


class PublishRequest(BaseModel):
    """JSON body. Unknown fields are refused, so a typo is noticed."""

    model_config = ConfigDict(extra="forbid")

    version: int = Field(ge=1)


# -------------------- helpers


def link_html(url: str, text: str) -> str:
    """A clickable link for Telegram, or plain text if it is not http(s)."""
    if is_web_link(url):
        return f'<a href="{escape_attribute(url)}">{escape_html(text)}</a>'
    return escape_html(url)


def linkedin_with_link(linkedin: str, url: str) -> str:
    """The LinkedIn post with [LÄNK] replaced by the article's URL."""
    if LINK_PLACEHOLDER in linkedin:
        return linkedin.replace(LINK_PLACEHOLDER, url)
    return f"{linkedin.rstrip()}\n\nLäs mer: {url}"


def format_messages(
    title: str, version: int, url: str, edit_url: str, post_status: str, linkedin: str
) -> list[dict]:
    """Telegram messages after publishing: the result, then the LinkedIn post."""
    headline = escape_html(shorten(title or "Utan rubrik", MAX_HEADLINE_CHARS))
    if post_status == "publish":
        lines = [
            f"<b>Publicerad v{version}: {headline}</b>",
            "",
            f"Artikeln ligger på webbplatsen: {link_html(url, url)}",
        ]
    else:
        lines = [
            f"<b>Utkast i WordPress v{version}: {headline}</b>",
            "",
            "Artikeln är sparad som utkast i WordPress. "
            f"Granska och publicera den där: {link_html(edit_url, 'Öppna i WordPress')}",
            "Länken i LinkedIn-inlägget fungerar när artikeln är publicerad.",
        ]
    messages = [{"text": "\n".join(lines), "parse_mode": "HTML"}]
    parts = split_into_parts(linkedin)
    for number, part in enumerate(parts, start=1):
        count = f" ({number}/{len(parts)})" if len(parts) > 1 else ""
        header = f"<b>LinkedIn-inlägg att posta{count}</b>"
        messages.append({"text": f"{header}\n\n{part}", "parse_mode": "HTML"})
    return messages


def check_status(publication: dict) -> None:
    """Raise 409 unless the post's status allows publishing."""
    post_id, status = publication["id"], publication["status"]
    if status == PUBLISHED_STATUS:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Post {post_id} is already published: "
                f"{publication.get('published_url') or 'URL not saved'}"
            ),
        )
    if status == REQUESTED_STATUS:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Post {post_id} is being published or the result is unknown. "
                "Check WordPress before trying again."
            ),
        )
    if status != PUBLISH_FROM:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Post {post_id} has status '{status}'. "
                f"Only a post in {PUBLISH_FROM} can be published."
            ),
        )


def read_and_check(source: str, post_id: int, version: int) -> tuple[dict, str]:
    """All checks that need no WordPress call. Returns (draft, title).

    Store errors become HTTP answers; the details stay in the server log.
    """
    try:
        publication = load_publication(source, post_id)
        check_status(publication)
        draft = load_latest_draft(source, post_id)
    except PostNotFound:
        raise HTTPException(status_code=404, detail="Post not found") from None
    except PostNotReady as error:
        raise HTTPException(status_code=409, detail=str(error)) from None
    except StoreError as error:
        logger.error("Could not read post %s: %s", post_id, error)
        raise HTTPException(status_code=502, detail="Could not read the post") from None

    if version != draft["version"]:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Version {version} is not the latest draft of post {post_id} "
                f"(latest is {draft['version']}). Read the latest version first."
            ),
        )
    problems = check_publishable(draft["article_text"], draft["linkedin_text"])
    if problems:
        raise HTTPException(
            status_code=409,
            detail="The draft cannot be published yet: " + " ".join(problems),
        )
    title, _ = split_headline(draft["article_text"])
    return draft, title


def release(source: str, post_id: int) -> None:
    """Set the status back to draft_generated. A failure is only logged."""
    try:
        cancel_publish_request(source, post_id)
    except StoreError as error:
        logger.error(
            "Post %s stays in %s: could not cancel (%s)",
            post_id,
            REQUESTED_STATUS,
            error,
        )


# -------------------- endpoint


@router.post("/drafts/{post_id}/publish")
def publish_draft(
    body: PublishRequest,
    post_id: int = Path(ge=1),
    dry_run: bool = Query(False),
) -> dict:
    """Publish the version Kisslo approved. See the module docstring."""
    source = os.getenv("TELEGRAM_SOURCE", "fixture").strip()
    if source not in SOURCES:
        logger.error("TELEGRAM_SOURCE must be fixture or supabase, not %r", source)
        raise HTTPException(status_code=500, detail="Server is not configured")
    try:
        settings = wordpress_settings()
    except WordPressConfigError as error:
        logger.error("WordPress is not configured: %s", error)
        raise HTTPException(
            status_code=500, detail="WordPress is not configured"
        ) from None

    draft, title = read_and_check(source, post_id, body.version)
    payload = build_payload(draft["article_text"], settings)

    if dry_run:
        return {
            "dry_run": True,
            "source": source,
            "post_id": post_id,
            "version": draft["version"],
            "wordpress_url": settings.url,
            "payload": payload,
        }

    with _in_progress_lock:
        if post_id in _in_progress:
            raise HTTPException(
                status_code=409,
                detail=f"Post {post_id} is already being published.",
            )
        _in_progress.add(post_id)
    try:
        try:
            approved = request_publish(source, post_id, body.version)
        except PostNotFound:
            raise HTTPException(status_code=404, detail="Post not found") from None
        except PostNotReady as error:
            raise HTTPException(status_code=409, detail=str(error)) from None
        except StoreError as error:
            logger.error("Could not lock post %s: %s", post_id, error)
            raise HTTPException(
                status_code=502, detail="Could not start publishing"
            ) from None

        try:
            wordpress_post = create_post(settings, payload)
        except WordPressError as error:
            logger.error("WordPress failed for post %s: %s", post_id, error)
            if error.not_created:
                release(source, post_id)
                raise HTTPException(
                    status_code=502,
                    detail="WordPress did not create the post. Try again later.",
                ) from None
            raise HTTPException(
                status_code=502,
                detail=(
                    "No answer from WordPress; the post may exist. "
                    "Check WordPress before trying again."
                ),
            ) from None

        try:
            publication = mark_published(source, post_id, approved, wordpress_post)
        except StoreError as error:
            # The post exists in WordPress. The status stays publish_requested,
            # so a new call cannot make a second post.
            logger.error(
                "Post %s was created in WordPress (id %s, %s) but not saved: %s",
                post_id,
                wordpress_post["id"],
                wordpress_post["link"],
                error,
            )
            raise HTTPException(
                status_code=502,
                detail=(
                    "The post was created in WordPress but the result "
                    "could not be saved."
                ),
            ) from None
    finally:
        with _in_progress_lock:
            _in_progress.discard(post_id)

    url = wordpress_post["link"]
    edit_url = edit_link(settings, wordpress_post["id"])
    wordpress_status = wordpress_post.get("status") or settings.post_status
    linkedin = linkedin_with_link(draft["linkedin_text"], url)
    return {
        "dry_run": False,
        "source": source,
        "post_id": post_id,
        "version": approved["version"],
        "draft_id": approved["draft_id"],
        "status": publication["status"],
        "wordpress_post_id": wordpress_post["id"],
        "wordpress_status": wordpress_status,
        "url": url,
        "edit_url": edit_url,
        "published_at": publication.get("published_at"),
        "linkedin": linkedin,
        "messages": format_messages(
            title, approved["version"], url, edit_url, wordpress_status, linkedin
        ),
    }
