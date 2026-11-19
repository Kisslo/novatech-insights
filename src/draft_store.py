"""Read a selected post and store draft versions (issue #30).

Used by the endpoint POST /drafts/{post_id} in telegram_api.py:
    post = load_post(source, post_id)       # 404 if it does not exist
    check_can_generate(post)                # 409 if the status does not allow it
    topic = load_topic(source, post["topic_id"])
    check_can_save(source)                  # before any money is spent
    ... write_draft() in draft_article.py ...
    saved = save_version(source, post, build_row(post, draft, stance, model))

Two sources, the same as TELEGRAM_SOURCE:
    fixture   posts from tests/fixtures/sample_posts.json and topics from
              tests/fixtures/sample_topics.json. A saved version becomes a
              JSON file in output/drafts/. The fixture file is never
              changed, so the post keeps its status.
    supabase  the posts table and the topic views through the REST API.
              A draft is saved with the database function save_post_draft
              (sql/010_create_post_drafts.sql, PR #60).

save_post_draft does everything in one transaction: it locks the post,
checks that its status allows a draft, gives the draft the next version
number, inserts it in post_drafts and sets the status to draft_generated.
Either all of it happens or none of it. The backend key may only read
post_drafts and call the function; it cannot insert or update rows itself.

Settings in .env (only for supabase):
    SUPABASE_URL, SUPABASE_KEY
    TOPICS_OVERVIEW_VIEW, TOPICS_ARTICLES_VIEW   (same as label_topics.py)
"""

import json
import os
import re
from datetime import datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
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
POSTS_TABLE = "posts"
DRAFTS_TABLE = "post_drafts"
SAVE_FUNCTION = "save_post_draft"
SOURCES = ("fixture", "supabase")

# A draft may be generated for a new angle, or again after Kisslo asked for
# changes (each generation is a new version). Not from draft_generated: a
# repeated call for a draft that is already waiting for Kisslo would only
# make a duplicate version. save_post_draft in sql/010 has the same rule.
GENERATE_FROM = ("angle_received", "changes_requested")
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


def error_message(error: HTTPError) -> str:
    """The "message" field of a Supabase error answer, or "" if there is none."""
    try:
        body = json.loads(error.read().decode("utf-8"))
    except OSError, ValueError:
        return ""
    message = body.get("message") if isinstance(body, dict) else None
    return message if isinstance(message, str) else ""


def call_function(name: str, arguments: dict) -> list[dict]:
    """Call a database function through /rest/v1/rpc/<name>. Returns its rows.

    The database answers HTTP 400 with the text of RAISE EXCEPTION when the
    function refuses. Those texts are turned into PostNotFound and
    PostNotReady, so the endpoint can answer 404 and 409.
    """
    base_url, key = supabase_settings()
    request = Request(
        f"{base_url.rstrip('/')}/rest/v1/rpc/{name}",
        data=json.dumps(arguments).encode("utf-8"),
        method="POST",
        headers={"apikey": key, "Content-Type": "application/json"},
    )
    try:
        with urlopen(request, timeout=SUPABASE_TIMEOUT_SECONDS) as response:
            rows = json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        message = error_message(error)
        if "does not exist" in message and message.startswith("Post "):
            raise PostNotFound(message) from error
        if "cannot receive a draft" in message:
            raise PostNotReady(message) from error
        if error.code in (401, 403):
            raise StoreError(
                f"Supabase refused to run '{name}' (HTTP {error.code}). "
                "Check SUPABASE_KEY and that the backend role may execute it."
            ) from error
        if error.code == 404:
            raise StoreError(
                f"Function '{name}' was not found in Supabase. Is migration 010 run?"
            ) from error
        raise StoreError(
            f"Supabase answered HTTP {error.code} for '{name}': {message[:200]}"
        ) from error
    except (URLError, OSError) as error:
        raise StoreError(f"Could not reach Supabase ({error}).") from error
    except json.JSONDecodeError as error:
        raise StoreError("Supabase did not answer with JSON.") from error
    if not isinstance(rows, list):
        raise StoreError(f"Unexpected answer from Supabase for '{name}'.")
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
            POSTS_TABLE,
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


def check_can_save(source: str) -> None:
    """Raise StoreError if a draft could not be saved (asked before Claude is called).

    For supabase: one small read from post_drafts, which fails if migration
    010 is missing or the key has no access. That way it is found before any
    money is spent. Fixture: nothing to check.
    """
    check_source(source)
    if source == "supabase":
        read_rows(DRAFTS_TABLE, {"select": "version", "limit": "1"})


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
    With supabase, save_post_draft does it in one transaction, so on any
    error nothing is saved and the status is unchanged. Raises PostNotFound
    or PostNotReady if the post is gone or its status changed meanwhile,
    and StoreError for other failures.
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

    rows = call_function(
        SAVE_FUNCTION,
        {
            "p_post_id": post_id,
            "p_article_text": row["article_text"],
            "p_linkedin_text": row["linkedin_text"],
            "p_reviewer_notes": row["reviewer_notes"],
            "p_source_news_ids": row["source_news_ids"],
            "p_stance": row["stance"],
        },
    )
    if len(rows) != 1 or "draft_id" not in rows[0] or "version" not in rows[0]:
        raise StoreError(f"Unexpected answer from {SAVE_FUNCTION} for post {post_id}.")
    return {
        "draft_id": rows[0]["draft_id"],
        "version": rows[0]["version"],
        "status": DRAFT_STATUS,
    }
