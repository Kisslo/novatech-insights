"""Read a selected post and store draft versions (issue #30).

Used by the endpoint POST /drafts/{post_id} in telegram_api.py:
    post = load_post(source, post_id)       # 404 if it does not exist
    check_can_generate(post)                # 409 if the status does not allow it
    topic = load_topic(source, post["topic_id"])
    ... write_draft() in draft_article.py ...
    saved = save_version(source, post, build_row(post, draft, stance, model))

Two sources, the same as TELEGRAM_SOURCE:
    fixture   posts from tests/fixtures/sample_posts.json and topics from
              tests/fixtures/sample_topics.json. A saved version becomes a
              JSON file in output/drafts/. The fixture file is never
              changed, so the post keeps its status.
    supabase  the posts table, the topic views and the post_drafts table
              through the REST API.

Saving in Supabase takes two requests: insert the draft row, then set the
post's status to draft_generated (only if the status still allows it). If
the second request fails, the draft row exists but the status is unchanged.
A database function that does both in one transaction is requested in
PR #60; when it exists, save_version() can call it instead.

Settings in .env (only for supabase):
    SUPABASE_URL, SUPABASE_KEY
    TOPICS_OVERVIEW_VIEW, TOPICS_ARTICLES_VIEW   (same as label_topics.py)
    POSTS_TABLE   (default posts)
    DRAFTS_TABLE  (default post_drafts)
"""

import json
import os
import re
from datetime import datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from content_tools import format_cost
from draft_article import build_notes_file
from label_topics import (
    DEFAULT_ARTICLES_VIEW,
    DEFAULT_FIXTURE,
    DEFAULT_OVERVIEW_VIEW,
    SUPABASE_TIMEOUT_SECONDS,
    ReadError,
    add_articles,
    normalize_topic,
    supabase_get,
    view_name,
)

PROJECT_FOLDER = Path(__file__).resolve().parent.parent
POSTS_FIXTURE = PROJECT_FOLDER / "tests" / "fixtures" / "sample_posts.json"
FIXTURE_OUTPUT_DIR = PROJECT_FOLDER / "output" / "drafts"
DEFAULT_POSTS_TABLE = "posts"
DEFAULT_DRAFTS_TABLE = "post_drafts"
SOURCES = ("fixture", "supabase")

# A draft may be generated for a new angle, and again after an earlier draft
# or after Kisslo asked for changes. Each generation is a new version.
GENERATE_FROM = ("angle_received", "draft_generated", "changes_requested")
DRAFT_STATUS = "draft_generated"

POST_FIELDS = "id,topic_id,status,kisslo_angle"
TOPIC_FIELDS = "id,score,article_count,source_count,label,why_relevant_sv,llm_relevance"
FIXTURE_FILE_PATTERN = re.compile(r"post_(\d+)_v(\d+)\.json")


class StoreError(Exception):
    """A post, topic or draft could not be read or saved.

    The message is written for the server log, not for the caller.
    """


class PostNotFound(StoreError):
    """There is no post with this id."""


class PostNotReady(StoreError):
    """The post exists, but its status does not allow a new draft."""


# -------------------- settings


def supabase_settings() -> tuple[str, str]:
    """Return (SUPABASE_URL, SUPABASE_KEY). Raises StoreError if one is missing."""
    base_url = os.getenv("SUPABASE_URL", "").strip()
    key = os.getenv("SUPABASE_KEY", "").strip()
    if not base_url or not key:
        raise StoreError("SUPABASE_URL and SUPABASE_KEY must be set in .env.")
    return base_url, key


def table_name(env_var: str, default: str) -> str:
    """Read a table or view name from .env and check that it is a plain name."""
    try:
        return view_name(env_var, default)
    except ReadError as error:
        raise StoreError(str(error)) from None


def read_rows(table: str, params: dict) -> list[dict]:
    """GET rows from Supabase. ReadError becomes StoreError."""
    base_url, key = supabase_settings()
    try:
        return supabase_get(base_url, key, table, params)
    except ReadError as error:
        raise StoreError(str(error)) from None


def write_rows(method: str, table: str, params: dict, values: dict) -> list[dict]:
    """POST (insert) or PATCH (update) in Supabase. Returns the changed rows.

    Supabase is asked to return the rows, so that "0 rows updated" can be
    seen by the caller instead of passing silently.
    """
    base_url, key = supabase_settings()
    query = urlencode(params, safe="(),.")
    request = Request(
        f"{base_url.rstrip('/')}/rest/v1/{table}?{query}",
        data=json.dumps(values).encode("utf-8"),
        method=method,
        headers={
            "apikey": key,
            "Content-Type": "application/json",
            "Prefer": "return=representation",
        },
    )
    try:
        with urlopen(request, timeout=SUPABASE_TIMEOUT_SECONDS) as response:
            rows = json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        if error.code in (401, 403):
            raise StoreError(
                f"Supabase refused to write to '{table}' (HTTP {error.code}). "
                "Check SUPABASE_KEY and the grants on the table."
            ) from error
        if error.code == 404:
            raise StoreError(f"Table '{table}' was not found in Supabase.") from error
        if error.code == 409:
            raise StoreError(
                f"Supabase refused the row in '{table}' (HTTP 409, conflict). "
                "Another draft was probably saved at the same time."
            ) from error
        raise StoreError(
            f"Supabase answered HTTP {error.code} when writing to '{table}'."
        ) from error
    except (URLError, OSError) as error:
        raise StoreError(f"Could not reach Supabase ({error}).") from error
    except json.JSONDecodeError as error:
        raise StoreError("Supabase did not answer with JSON.") from error
    if not isinstance(rows, list):
        raise StoreError(f"Unexpected answer from Supabase for '{table}'.")
    return rows


def check_source(source: str) -> None:
    if source not in SOURCES:
        raise StoreError(f"Source must be fixture or supabase, not '{source}'.")


# -------------------- reading


def load_post(source: str, post_id: int) -> dict:
    """Return the post as {"id", "topic_id", "status", "kisslo_angle"}.

    Raises PostNotFound if there is no such post.
    """
    check_source(source)
    if source == "supabase":
        posts = read_rows(
            table_name("POSTS_TABLE", DEFAULT_POSTS_TABLE),
            {"select": POST_FIELDS, "id": f"eq.{post_id}"},
        )
    else:
        with POSTS_FIXTURE.open(encoding="utf-8") as f:
            posts = [p for p in json.load(f)["posts"] if p["id"] == post_id]
    if not posts:
        raise PostNotFound(f"Post {post_id} was not found.")
    return posts[0]


def check_can_generate(post: dict) -> None:
    """Raise PostNotReady unless the post's status allows a new draft."""
    if post["status"] not in GENERATE_FROM:
        raise PostNotReady(
            f"Post {post['id']} has status '{post['status']}'. "
            f"A draft can be generated from: {', '.join(GENERATE_FROM)}."
        )


def load_topic(source: str, topic_id: int) -> dict:
    """Return the post's topic with label, why_relevant_sv and top articles.

    Same checks as the top list (normalize_topic): the topic must have
    articles, and each article a title, source and link.
    """
    check_source(source)
    if source == "supabase":
        rows = read_rows(
            table_name("TOPICS_OVERVIEW_VIEW", DEFAULT_OVERVIEW_VIEW),
            {"select": TOPIC_FIELDS, "id": f"eq.{topic_id}"},
        )
        if rows:
            base_url, key = supabase_settings()
            articles_view = table_name("TOPICS_ARTICLES_VIEW", DEFAULT_ARTICLES_VIEW)
            try:
                rows = add_articles(base_url, key, articles_view, rows)
            except ReadError as error:
                raise StoreError(str(error)) from None
    else:
        with DEFAULT_FIXTURE.open(encoding="utf-8") as f:
            rows = [t for t in json.load(f)["topics"] if t["id"] == topic_id]
    if not rows:
        raise StoreError(f"Topic {topic_id} was not found.")
    # The score is not used for a draft, but normalize_topic requires a number.
    raw = {**rows[0], "score": rows[0].get("score") or 0}
    try:
        return normalize_topic(raw)
    except (ValueError, TypeError) as error:
        raise StoreError(f"Topic {topic_id} cannot be used: {error}") from None


# -------------------- saving


def build_row(post: dict, draft: dict, stance: str, model: str) -> dict:
    """The post_drafts row for one draft from write_draft(), without version.

    The reviewer notes are one text: the automatic checks and warnings,
    Claude's notes, what the review step changed, and the run details.
    They are stored in their own column and are never part of article_text.
    """
    info = {
        "Stance": stance,
        "Model": model,
        "Reviewed": "yes" if draft["reviewed"] else "no",
        "Tokens": f"{draft['tokens_in']} in / {draft['tokens_out']} out",
        "Cost": format_cost(draft["cost"]),
    }
    return {
        "post_id": post["id"],
        "article_text": draft["article"],
        "linkedin_text": draft["linkedin"],
        "reviewer_notes": build_notes_file(
            draft["notes"],
            draft["warnings"],
            draft["stats"],
            info,
            draft["review_notes"],
        ),
        "source_news_ids": draft["source_news_ids"],
        "stance": stance,
    }


def next_fixture_version(post_id: int) -> int:
    """1 + the highest version among the saved files for this post."""
    versions = [0]
    if FIXTURE_OUTPUT_DIR.exists():
        for path in FIXTURE_OUTPUT_DIR.iterdir():
            match = FIXTURE_FILE_PATTERN.fullmatch(path.name)
            if match and int(match.group(1)) == post_id:
                versions.append(int(match.group(2)))
    return max(versions) + 1


def save_version(source: str, post: dict, row: dict) -> dict:
    """Save the draft as the post's next version and set status draft_generated.

    Returns {"draft_id", "version", "status"}. draft_id is None for fixture.
    Raises StoreError if the draft could not be saved, or if it was saved
    but the status could not be changed (the message says which).
    """
    check_source(source)
    post_id = post["id"]
    if source == "fixture":
        version = next_fixture_version(post_id)
        FIXTURE_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        data = {
            **row,
            "version": version,
            "status": DRAFT_STATUS,
            "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        }
        path = FIXTURE_OUTPUT_DIR / f"post_{post_id}_v{version}.json"
        path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        return {"draft_id": None, "version": version, "status": DRAFT_STATUS}

    drafts = table_name("DRAFTS_TABLE", DEFAULT_DRAFTS_TABLE)
    posts = table_name("POSTS_TABLE", DEFAULT_POSTS_TABLE)
    latest = read_rows(
        drafts,
        {
            "select": "version",
            "post_id": f"eq.{post_id}",
            "order": "version.desc",
            "limit": "1",
        },
    )
    version = latest[0]["version"] + 1 if latest else 1
    inserted = write_rows(
        "POST", drafts, {"select": "id,version"}, {**row, "version": version}
    )
    if len(inserted) != 1:
        raise StoreError(f"The draft for post {post_id} was not saved.")
    # Only change the status if it is still one we may generate from, so a
    # status that changed during the generation is not overwritten.
    updated = write_rows(
        "PATCH",
        posts,
        {
            "id": f"eq.{post_id}",
            "status": f"in.({','.join(GENERATE_FROM)})",
            "select": "id",
        },
        {"status": DRAFT_STATUS},
    )
    if len(updated) != 1:
        raise StoreError(
            f"Draft version {version} for post {post_id} was saved, but the "
            f"status could not be set to {DRAFT_STATUS} (it changed meanwhile)."
        )
    return {"draft_id": inserted[0]["id"], "version": version, "status": DRAFT_STATUS}
