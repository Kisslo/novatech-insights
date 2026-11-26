"""Endpoints for n8n: the buttons Ändra and Skippa under a draft (issue #67).

    POST /drafts/{post_id}/revise            with header X-API-Key
    POST /drafts/{post_id}/revise?dry_run=true
    JSON body: {"version": <n>, "change_request": "<Kisslo's text>"}

    POST /drafts/{post_id}/keep              with header X-API-Key
    JSON body: {"version": <n>}

n8n calls /revise when Kisslo has pressed Ändra (revise:<post_id>:<n>) and
written what he wants changed, and /keep when he presses Skippa
(keep:<post_id>:<n>). n8n never writes to Supabase itself (decided with
Turker 25 Nov). The routers are added to the app in telegram_api.py, which
also adds the API key check.

What /revise does:
1. Checks before any money is spent: the post exists, its status is
   draft_generated (or changes_requested, see below), the version is the
   latest draft, and its sources are still in the topic.
2. Saves the change request on that version and sets changes_requested
   (request_draft_changes, migration 014).
3. Writes the next version with two Claude calls (draft_article.py): call 1
   changes the previous version according to the change request, call 2
   reviews it, with the same style guide and checks as POST /drafts. Only
   the sources of the previous version are used, with its stance.
4. Saves it with save_post_draft (status draft_generated) and returns the
   Telegram messages in the same format as POST /drafts, with new buttons.

If step 3 or 4 fails, the post stays in changes_requested. A new /revise
for the same version then skips step 2 and writes the version with the
change request of the new call. The change request is also added to the
reviewer notes of the new version, so each version shows what it answers.

What /keep does: keep_draft sets draft_kept. The draft stays in
post_drafts and nothing is published. Returns a short Telegram message.

Answers:
    200  done (or dry run)
    401  wrong or missing API key
    404  no such post
    409  wrong status, old version, the sources are gone, or a draft is
         already being written for this post
    422  invalid body, for example a missing version or an empty text
    500  TELEGRAM_SOURCE is invalid
    502  Supabase or Claude failed

A real /revise takes 30–60 seconds and costs money. dry_run=true makes no
call to Claude and changes nothing: it checks the post and returns the
prompt and an estimated cost.
"""

import logging
import os

from fastapi import APIRouter, HTTPException, Path, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator

from content_tools import ClaudeError, call_claude
from draft_api import (
    _in_progress,
    _in_progress_lock,
    estimate_draft_cost,
    format_messages,
)
from draft_article import (
    DEFAULT_EFFORT,
    DEFAULT_MODEL,
    DEFAULT_STANCE,
    MAX_CHANGE_REQUEST_CHARS,
    REVISE_SYSTEM_PROMPT,
    STANCES,
    build_revise_prompt,
    check_inputs,
    revise_draft,
)
from draft_store import (
    DRAFT_STATUS,
    SOURCES,
    PostNotFound,
    PostNotReady,
    StoreError,
    build_row,
    check_can_save,
    load_topic,
)
from revise_store import (
    CHANGES_STATUS,
    KEPT_STATUS,
    add_change_request_to_notes,
    keep,
    load_draft_for_revision,
    load_post_state,
    request_changes,
    save_revision,
    topic_with_sources,
)

# A revision may start from a draft that waits for Kisslo, or again after a
# failed attempt that left the post in changes_requested.
REVISE_FROM = (DRAFT_STATUS, CHANGES_STATUS)

logger = logging.getLogger("revise_api")
router = APIRouter()


class KeepRequest(BaseModel):
    """JSON body for /keep. Unknown fields are refused, so a typo is noticed."""

    model_config = ConfigDict(extra="forbid")

    version: int = Field(ge=1)


class ReviseRequest(BaseModel):
    """JSON body for /revise. Unknown fields are refused, so a typo is noticed."""

    model_config = ConfigDict(extra="forbid")

    version: int = Field(ge=1)
    change_request: str = Field(max_length=MAX_CHANGE_REQUEST_CHARS)

    @field_validator("change_request")
    @classmethod
    def not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("change_request must not be empty")
        return value


# -------------------- helpers


def get_source() -> str:
    """TELEGRAM_SOURCE, or 500 if it is not fixture or supabase."""
    source = os.getenv("TELEGRAM_SOURCE", "fixture").strip()
    if source not in SOURCES:
        logger.error("TELEGRAM_SOURCE must be fixture or supabase, not %r", source)
        raise HTTPException(status_code=500, detail="Server is not configured")
    return source


def store_error(post_id: int, error: StoreError, what: str) -> HTTPException:
    """404, 409 or 502 for a store error. Details only go to the server log."""
    if isinstance(error, PostNotFound):
        return HTTPException(status_code=404, detail="Post not found")
    if isinstance(error, PostNotReady):
        return HTTPException(status_code=409, detail=str(error))
    logger.error("%s for post %s: %s", what, post_id, error)
    return HTTPException(status_code=502, detail=what)


def read_for_revision(source: str, post_id: int, version: int) -> tuple:
    """All checks that need no Claude call. Returns (post, draft, topic, stance)."""
    try:
        post = load_post_state(source, post_id)
        if post["status"] not in REVISE_FROM:
            raise PostNotReady(
                f"Post {post_id} has status '{post['status']}'. "
                f"A draft can be revised from: {', '.join(REVISE_FROM)}."
            )
        draft = load_draft_for_revision(source, post_id)
        if version != draft["version"]:
            raise PostNotReady(
                f"Version {version} is not the latest draft of post {post_id} "
                f"(latest is {draft['version']}). Read the latest version first."
            )
        topic = topic_with_sources(
            load_topic(source, post["topic_id"]), draft["source_news_ids"]
        )
    except StoreError as error:
        raise store_error(post_id, error, "Could not read the post") from None

    stance = draft["stance"] or DEFAULT_STANCE
    try:
        if stance not in STANCES:
            raise ValueError(f"Version {version} has an unknown stance '{stance}'.")
        check_inputs(topic, post.get("kisslo_angle") or "", stance)
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from None
    return post, draft, topic, stance


# -------------------- Skippa


@router.post("/drafts/{post_id}/keep")
def keep_draft(body: KeepRequest, post_id: int = Path(ge=1)) -> dict:
    """Skippa: keep the draft and do nothing more. See the module docstring."""
    source = get_source()
    try:
        kept = keep(source, post_id, body.version)
    except StoreError as error:
        raise store_error(post_id, error, "Could not keep the draft") from None
    text = (
        f"<b>Utkastet är sparat (v{kept['version']})</b>\n\n"
        "Inget publiceras. Utkastet finns kvar i databasen."
    )
    return {
        "source": source,
        "post_id": post_id,
        "draft_id": kept["draft_id"],
        "version": kept["version"],
        "status": KEPT_STATUS,
        "messages": [{"text": text, "parse_mode": "HTML"}],
    }


# -------------------- Ändra


@router.post("/drafts/{post_id}/revise")
def revise(
    body: ReviseRequest,
    post_id: int = Path(ge=1),
    dry_run: bool = Query(False),
) -> dict:
    """Write a new version from Kisslo's change request. See the module docstring."""
    source = get_source()
    model = os.getenv("CONTENT_WRITER_MODEL", DEFAULT_MODEL)
    effort = os.getenv("CONTENT_WRITER_EFFORT", DEFAULT_EFFORT)
    post, draft, topic, stance = read_for_revision(source, post_id, body.version)
    angle = post.get("kisslo_angle") or ""
    previous = {"article": draft["article_text"], "linkedin": draft["linkedin_text"]}

    if dry_run:
        prompt = build_revise_prompt(
            topic, angle, stance, previous, body.change_request
        )
        return {
            "dry_run": True,
            "source": source,
            "post_id": post_id,
            "based_on_version": draft["version"],
            "status": post["status"],
            "stance": stance,
            "model": model,
            "estimate": estimate_draft_cost(
                model, prompt, system_prompt=REVISE_SYSTEM_PROMPT
            ),
            "prompt": prompt,
        }

    # The same lock as POST /drafts, so the two cannot write for the same
    # post at the same time.
    with _in_progress_lock:
        if post_id in _in_progress:
            raise HTTPException(
                status_code=409,
                detail=f"A draft is already being written for post {post_id}.",
            )
        _in_progress.add(post_id)
    try:
        try:
            check_can_save(source)
            if post["status"] == DRAFT_STATUS:
                request_changes(source, post_id, body.version, body.change_request)
            # Otherwise a retry: the post is already in changes_requested.
        except StoreError as error:
            raise store_error(post_id, error, "Could not save the change") from None
        try:
            revised = revise_draft(
                topic,
                angle,
                stance,
                previous,
                body.change_request,
                model,
                effort,
                call=call_claude,
            )
        except (ClaudeError, ValueError) as error:
            logger.error("Could not revise post %s: %s", post_id, error)
            raise HTTPException(
                status_code=502, detail="Could not write the new version"
            ) from None
        row = build_row(post, revised, stance, model)
        row["reviewer_notes"] = add_change_request_to_notes(
            row["reviewer_notes"], body.change_request, draft["version"]
        )
        try:
            saved = save_revision(source, post, row)
        except StoreError as error:
            raise store_error(post_id, error, "Could not save the draft") from None
    finally:
        with _in_progress_lock:
            _in_progress.discard(post_id)

    return {
        "dry_run": False,
        "source": source,
        "post_id": post_id,
        "topic_id": topic["id"],
        "based_on_version": draft["version"],
        "draft_id": saved["draft_id"],
        "version": saved["version"],
        "status": saved["status"],
        "stance": stance,
        "reviewed": revised["reviewed"],
        "stats": revised["stats"],
        "warnings": revised["warnings"],
        "cost_usd": None if revised["cost"] is None else round(revised["cost"], 4),
        "messages": format_messages(
            revised, row["reviewer_notes"], post_id, saved["version"]
        ),
        "article": revised["article"],
        "linkedin": revised["linkedin"],
        "reviewer_notes": row["reviewer_notes"],
        "source_news_ids": revised["source_news_ids"],
    }
