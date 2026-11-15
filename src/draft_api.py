"""Endpoint for n8n: write an article draft for a selected post (issue #30).

    POST /drafts/{post_id}            with header X-API-Key: <TELEGRAM_API_KEY>
    POST /drafts/{post_id}?dry_run=true
    Optional JSON body: {"stance": "agree"} or {"stance": "rebut"}

The router is added to the app in telegram_api.py, which also adds the API
key check. What one call does:
1. Read the post, check its status and read its topic (draft_store.py),
   and check that a draft can be saved.
2. Write and review the draft with two Claude calls (draft_article.py).
3. Save the draft as a new version and set status draft_generated.
4. Return the texts and a short preview that n8n can send to Telegram.

Answers:
    200  draft saved (or dry run)
    401  wrong or missing API key
    404  no such post
    409  the post's status does not allow a draft, the topic or angle cannot
         be used, or a draft is already being written for this post
    422  invalid body, for example an unknown stance
    502  Supabase or Claude failed; no draft was saved by this call

A real call takes 30–60 seconds and costs money. dry_run=true makes no call
to Claude and saves nothing: it checks the post and returns the prompt and
an estimated cost.

Settings in .env: TELEGRAM_SOURCE (fixture or supabase, shared with
/telegram/top), CONTENT_WRITER_MODEL, CONTENT_WRITER_EFFORT and the
settings in draft_store.py.
"""

import logging
import os
import threading
from typing import Literal

from fastapi import APIRouter, HTTPException, Path, Query
from pydantic import BaseModel, ConfigDict

from content_tools import ClaudeError, call_claude, estimate_cost
from draft_article import (
    DEFAULT_EFFORT,
    DEFAULT_MODEL,
    DEFAULT_STANCE,
    MAX_OUTPUT_TOKENS,
    REVIEW_MAX_OUTPUT_TOKENS,
    REVIEW_SYSTEM_PROMPT,
    SYSTEM_PROMPT,
    UNVERIFIED_TAG,
    build_draft_prompt,
    build_review_prompt,
    check_inputs,
    write_draft,
)
from draft_store import (
    SOURCES,
    PostNotFound,
    PostNotReady,
    StoreError,
    build_row,
    check_can_generate,
    check_can_save,
    load_post,
    load_topic,
    save_version,
)
from telegram_format import MAX_MESSAGE_CHARS, escape_html, shorten

MAX_PREVIEW_HEADLINE_CHARS = 200
MAX_PREVIEW_INTRO_CHARS = 600
MAX_PREVIEW_LINKEDIN_CHARS = 1500

logger = logging.getLogger("draft_api")
router = APIRouter()

# Posts that a draft is being written for right now. A second request for
# the same post (for example a double click in Telegram) is refused, so it
# does not pay for the same draft twice. Works because the API runs as one
# process.
_in_progress: set[int] = set()
_in_progress_lock = threading.Lock()


class DraftRequest(BaseModel):
    """Optional JSON body. Unknown fields are refused, so a typo is noticed."""

    model_config = ConfigDict(extra="forbid")

    stance: Literal["agree", "rebut"] = DEFAULT_STANCE


# -------------------- helpers


def estimate_draft_cost(model: str, prompt: str, article_chars: int = 6000) -> dict:
    """Rough highest cost of both calls: ~4 characters per token, all output used.

    The review prompt does not exist before call 1, so its input is estimated
    from a typical article length. Cost is None if the model's price is unknown.
    """
    write_in = (len(SYSTEM_PROMPT) + len(prompt)) // 4
    review_prompt = build_review_prompt("", "")
    review_in = (len(REVIEW_SYSTEM_PROMPT) + len(review_prompt) + article_chars) // 4
    write_cost = estimate_cost(model, write_in, MAX_OUTPUT_TOKENS)
    review_cost = estimate_cost(model, review_in, REVIEW_MAX_OUTPUT_TOKENS)
    total = (
        None if write_cost is None or review_cost is None else write_cost + review_cost
    )
    return {
        "input_tokens": write_in + review_in,
        "max_output_tokens": MAX_OUTPUT_TOKENS + REVIEW_MAX_OUTPUT_TOKENS,
        "max_cost_usd": None if total is None else round(total, 4),
    }


def headline_and_intro(article: str) -> tuple[str, str]:
    """The "# " headline and the first paragraph after it ("" if missing)."""
    headline, intro = "", ""
    for line in article.splitlines():
        text = line.strip()
        if text.startswith("# ") and not headline:
            headline = text[2:].strip()
        elif text and not text.startswith("#"):
            intro = text
            break
    return headline, intro


def format_preview(draft: dict, version: int) -> dict:
    """A short Telegram message (HTML) about the draft: headline, intro,
    LinkedIn text and the numbers Kisslo needs before he opens the full text.

    Text is shortened first and escaped afterwards, like in telegram_format.
    """
    headline, intro = headline_and_intro(draft["article"])
    stats = draft["stats"]
    title = shorten(headline or "Utan rubrik", MAX_PREVIEW_HEADLINE_CHARS)
    lines = [
        f"<b>Utkast v{version}: {escape_html(title)}</b>",
        "",
        escape_html(shorten(intro, MAX_PREVIEW_INTRO_CHARS)),
        "",
        "<b>LinkedIn</b>",
        escape_html(shorten(draft["linkedin"], MAX_PREVIEW_LINKEDIN_CHARS)),
        "",
        f"Ord: {stats['words']}"
        f" · Avsnitt: {stats['sections']}"
        f" · {escape_html(UNVERIFIED_TAG)}: {stats['unverified']}"
        f" · Varningar: {len(draft['warnings'])}",
    ]
    if not draft["reviewed"]:
        lines.append("Obs: granskningssteget misslyckades, texten är inte granskad.")
    text = "\n".join(lines)
    return {"text": text[:MAX_MESSAGE_CHARS], "parse_mode": "HTML"}


def read_post_and_topic(source: str, post_id: int) -> tuple[dict, dict]:
    """Read the post and its topic. Store errors become HTTP answers.

    The details stay in the server log; the caller only gets a short message.
    """
    try:
        post = load_post(source, post_id)
        check_can_generate(post)
        topic = load_topic(source, post["topic_id"])
    except PostNotFound:
        raise HTTPException(status_code=404, detail="Post not found") from None
    except PostNotReady as error:
        raise HTTPException(status_code=409, detail=str(error)) from None
    except StoreError as error:
        logger.error("Could not read post %s: %s", post_id, error)
        raise HTTPException(status_code=502, detail="Could not read the post") from None
    return post, topic


# -------------------- endpoint


@router.post("/drafts/{post_id}")
def create_draft(
    post_id: int = Path(ge=1),
    dry_run: bool = Query(False),
    body: DraftRequest | None = None,
) -> dict:
    """Write, review and save a draft for the post. See the module docstring."""
    source = os.getenv("TELEGRAM_SOURCE", "fixture").strip()
    if source not in SOURCES:
        logger.error("TELEGRAM_SOURCE must be fixture or supabase, not %r", source)
        raise HTTPException(status_code=500, detail="Server is not configured")
    stance = body.stance if body is not None else DEFAULT_STANCE
    model = os.getenv("CONTENT_WRITER_MODEL", DEFAULT_MODEL)
    effort = os.getenv("CONTENT_WRITER_EFFORT", DEFAULT_EFFORT)

    post, topic = read_post_and_topic(source, post_id)
    angle = post.get("kisslo_angle") or ""
    try:
        check_inputs(topic, angle, stance)
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from None

    if dry_run:
        prompt = build_draft_prompt(topic, angle, stance)
        return {
            "dry_run": True,
            "source": source,
            "post_id": post_id,
            "topic_id": topic["id"],
            "stance": stance,
            "model": model,
            "estimate": estimate_draft_cost(model, prompt),
            "prompt": prompt,
        }

    with _in_progress_lock:
        if post_id in _in_progress:
            raise HTTPException(
                status_code=409,
                detail=f"A draft is already being written for post {post_id}.",
            )
        _in_progress.add(post_id)
    try:
        try:
            # Asked before Claude is called, so that a missing drafts table
            # is found before any money is spent.
            check_can_save(source)
        except StoreError as error:
            logger.error("Drafts cannot be saved: %s", error)
            raise HTTPException(
                status_code=502, detail="Drafts cannot be saved"
            ) from None
        try:
            draft = write_draft(topic, angle, stance, model, effort, call=call_claude)
        except (ClaudeError, ValueError) as error:
            logger.error("Could not write a draft for post %s: %s", post_id, error)
            raise HTTPException(
                status_code=502, detail="Could not write the draft"
            ) from None
        row = build_row(post, draft, stance, model)
        try:
            saved = save_version(source, post, row)
        except StoreError as error:
            logger.error("Could not save the draft for post %s: %s", post_id, error)
            raise HTTPException(
                status_code=502, detail="Could not save the draft"
            ) from None
    finally:
        with _in_progress_lock:
            _in_progress.discard(post_id)

    return {
        "dry_run": False,
        "source": source,
        "post_id": post_id,
        "topic_id": topic["id"],
        "draft_id": saved["draft_id"],
        "version": saved["version"],
        "status": saved["status"],
        "stance": stance,
        "reviewed": draft["reviewed"],
        "stats": draft["stats"],
        "warnings": draft["warnings"],
        "cost_usd": None if draft["cost"] is None else round(draft["cost"], 4),
        "preview": format_preview(draft, saved["version"]),
        "article": draft["article"],
        "linkedin": draft["linkedin"],
        "reviewer_notes": row["reviewer_notes"],
        "source_news_ids": draft["source_news_ids"],
    }
