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
4. Return the texts and a list of ready Telegram messages: the article,
   the LinkedIn post and the reviewer notes in parts that fit Telegram, and
   last a message with the buttons Publicera, Ändra and Skippa.

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
import re
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
from telegram_format import (
    MAX_CALLBACK_BYTES,
    MAX_MESSAGE_CHARS,
    escape_html,
    shorten,
)

MAX_HEADLINE_CHARS = 200
# Room under Telegram's limit of 4,096 characters for the part's title line.
MAX_PART_CHARS = MAX_MESSAGE_CHARS - 200
HEADING_PATTERN = re.compile(r"#{1,6}\s+(.*)")
BOLD_PATTERN = re.compile(r"\*\*(.+?)\*\*")


# Buttons under the draft in Telegram (decided 16 Nov). n8n handles the
# presses. The prefixes differ from write/skip for topics, so n8n can tell a
# topic from a draft. The version is part of the data, so a press always
# applies to the exact version Kisslo read.
DRAFT_BUTTONS = (
    ("Publicera", "publish"),  # publish this version on the website
    ("Ändra", "revise"),  # Kisslo writes what to change, a new version is made
    ("Skippa", "keep"),  # keep the draft, do nothing more
)

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


def draft_buttons(post_id: int, version: int) -> list[dict]:
    """The three buttons with callback_data "<action>:<post_id>:<version>"."""
    buttons = []
    for text, action in DRAFT_BUTTONS:
        data = f"{action}:{post_id}:{version}"
        if len(data.encode("utf-8")) > MAX_CALLBACK_BYTES:
            raise ValueError(f"callback_data is longer than 64 bytes: {data}")
        buttons.append({"text": text, "callback_data": data})
    return buttons


def markdown_blocks(markdown: str) -> list[str]:
    """Markdown as Telegram HTML, one block per paragraph.

    Headings and **bold** become <b>; everything else is escaped text, so
    nothing in the draft can be read as a Telegram tag.
    """
    blocks = []
    for paragraph in re.split(r"\n\s*\n", markdown.strip()):
        lines = []
        for line in paragraph.splitlines():
            heading = HEADING_PATTERN.fullmatch(line.strip())
            if heading:
                lines.append(f"<b>{escape_html(heading.group(1))}</b>")
            else:
                lines.append(BOLD_PATTERN.sub(r"<b>\1</b>", escape_html(line.rstrip())))
        blocks.append("\n".join(lines))
    return blocks


def split_long_block(block: str, limit: int) -> list[str]:
    """Cut a block longer than `limit` at line breaks, or at spaces.

    A single line that is still too long loses its <b> tags first, so a cut
    can never leave a tag open.
    """
    pieces, current = [], ""
    for line in block.split("\n"):
        if len(line) > limit:
            line = line.replace("<b>", "").replace("</b>", "")
        words = line.split(" ") if len(line) > limit else [line]
        for i, word in enumerate(words):
            joiner = "" if not current else ("\n" if i == 0 else " ")
            if current and len(current) + len(joiner) + len(word) > limit:
                pieces.append(current)
                current, joiner = "", ""
            current += joiner + word[:limit]
    if current:
        pieces.append(current)
    return pieces


def split_into_parts(markdown: str, limit: int = MAX_PART_CHARS) -> list[str]:
    """Markdown as Telegram HTML parts of at most `limit` characters.

    Parts are cut between paragraphs, so a paragraph is only cut when it is
    longer than a whole part.
    """
    parts, current = [], ""
    for block in markdown_blocks(markdown):
        for piece in split_long_block(block, limit) if len(block) > limit else [block]:
            if current and len(current) + 2 + len(piece) > limit:
                parts.append(current)
                current = ""
            current = f"{current}\n\n{piece}" if current else piece
    if current:
        parts.append(current)
    return parts


def format_decision(draft: dict, post_id: int, version: int) -> dict:
    """The last message: the numbers and the buttons Publicera, Ändra, Skippa."""
    headline, _ = headline_and_intro(draft["article"])
    stats = draft["stats"]
    title = shorten(headline or "Utan rubrik", MAX_HEADLINE_CHARS)
    lines = [
        f"<b>Utkast v{version}: {escape_html(title)}</b>",
        "",
        f"Ord: {stats['words']}"
        f" · Avsnitt: {stats['sections']}"
        f" · {escape_html(UNVERIFIED_TAG)}: {stats['unverified']}"
        f" · Varningar: {len(draft['warnings'])}",
    ]
    if not draft["reviewed"]:
        lines.append("Obs: granskningssteget misslyckades, texten är inte granskad.")
    lines += ["", "Läs utkastet ovan och välj Publicera, Ändra eller Skippa."]
    return {
        "text": "\n".join(lines),
        "parse_mode": "HTML",
        "buttons": draft_buttons(post_id, version),
    }


def format_messages(
    draft: dict, reviewer_notes: str, post_id: int, version: int
) -> list[dict]:
    """All Telegram messages for one draft, in the order n8n sends them.

    First the article, then the LinkedIn post, then the reviewer notes, each
    split into parts that fit in one Telegram message, and last a short
    message with the buttons. Kisslo reads everything before he chooses, and
    the buttons name the exact version he read (decided with Turker 16 Nov).
    """
    sections = [
        ("Artikel", draft["article"]),
        ("LinkedIn", draft["linkedin"]),
        ("Anteckningar för granskning (publiceras inte)", reviewer_notes),
    ]
    messages = []
    for title, text in sections:
        parts = split_into_parts(text)
        for number, part in enumerate(parts, start=1):
            count = f" ({number}/{len(parts)})" if len(parts) > 1 else ""
            header = f"<b>Utkast v{version} · {title}{count}</b>"
            messages.append({"text": f"{header}\n\n{part}", "parse_mode": "HTML"})
    messages.append(format_decision(draft, post_id, version))
    return messages


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
        except PostNotFound:
            raise HTTPException(status_code=404, detail="Post not found") from None
        except PostNotReady as error:
            # The status changed while the draft was being written.
            raise HTTPException(status_code=409, detail=str(error)) from None
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
        "messages": format_messages(
            draft, row["reviewer_notes"], post_id, saved["version"]
        ),
        "article": draft["article"],
        "linkedin": draft["linkedin"],
        "reviewer_notes": row["reviewer_notes"],
        "source_news_ids": draft["source_news_ids"],
    }
