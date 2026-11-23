"""Read and store the publishing of a draft (issue #81).

Used by the endpoint POST /drafts/{post_id}/publish:
    publication = load_publication(source, post_id)   # 404 if no such post
    draft = load_latest_draft(source, post_id)        # the version to compare
    approved = request_publish(source, post_id, version)
    ... create the post in WordPress (wordpress_publish.py) ...
    mark_published(source, post_id, approved, wordpress_post)
    (or cancel_publish_request(source, post_id) if WordPress surely
    did not create the post)

Publishing is saved in two steps so that a retry can never create a second
WordPress post:
1. request_publish locks the post, checks that its status is
   draft_generated and that the version is the latest draft, and sets the
   status to publish_requested. A second call is refused from here on.
2. After WordPress has created the post, mark_post_published sets the
   status to published and saves the approved draft, the WordPress post id,
   the URL and the time.
If WordPress surely did not create the post (it refused, or could not be
reached), cancel_publish_request sets the status back to draft_generated,
so Kisslo can try again. If the answer was lost (a timeout), the status
stays publish_requested and someone checks WordPress by hand.

Two sources, the same as TELEGRAM_SOURCE:
    fixture   drafts from output/drafts/ (written by POST /drafts) and the
              publishing state in output/published/post_<id>.json. The
              fixture posts file is never changed. A fixture post that has a
              saved draft counts as draft_generated.
    supabase  the posts and post_drafts tables, and the database functions
              request_publish, mark_post_published and
              cancel_publish_request (migration 013, Nosheen).
"""

import json
from datetime import datetime
from pathlib import Path

import draft_store
from draft_store import (
    DRAFT_STATUS,
    DRAFTS_TABLE,
    FIXTURE_FILE_PATTERN,
    GENERATE_FROM,
    POSTS_TABLE,
    PROJECT_FOLDER,
    PostNotFound,
    PostNotReady,
    StoreError,
    call_function,
    check_source,
    load_post,
    read_rows,
)

FIXTURE_PUBLISHED_DIR = PROJECT_FOLDER / "output" / "published"
PUBLISH_MIGRATION = "013"
REQUEST_FUNCTION = "request_publish"
MARK_FUNCTION = "mark_post_published"
CANCEL_FUNCTION = "cancel_publish_request"

PUBLISH_FROM = DRAFT_STATUS  # only a draft that waits for Kisslo
REQUESTED_STATUS = "publish_requested"
PUBLISHED_STATUS = "published"

PUBLICATION_FIELDS = (
    "id,status,approved_draft_id,wordpress_post_id,published_url,published_at"
)
DRAFT_FIELDS = "id,version,article_text,linkedin_text"


# -------------------- fixture files


def draft_dir() -> Path:
    """Where POST /drafts saves fixture drafts (read at call time for tests)."""
    return draft_store.FIXTURE_OUTPUT_DIR


def fixture_versions(post_id: int) -> dict[int, Path]:
    """The saved fixture drafts for the post: {version: file}."""
    versions = {}
    if draft_dir().exists():
        for path in draft_dir().iterdir():
            match = FIXTURE_FILE_PATTERN.fullmatch(path.name)
            if match and int(match.group(1)) == post_id:
                versions[int(match.group(2))] = path
    return versions


def published_file(post_id: int) -> Path:
    return FIXTURE_PUBLISHED_DIR / f"post_{post_id}.json"


def write_published_file(post_id: int, data: dict) -> None:
    FIXTURE_PUBLISHED_DIR.mkdir(parents=True, exist_ok=True)
    published_file(post_id).write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


# -------------------- reading


def load_publication(source: str, post_id: int) -> dict:
    """The post's status and publishing result.

    Returns {"id", "status", "approved_draft_id", "wordpress_post_id",
    "published_url", "published_at"}; the last four are None until the post
    is published. Raises PostNotFound if there is no such post.
    """
    check_source(source)
    if source == "supabase":
        rows = read_rows(
            POSTS_TABLE, {"select": PUBLICATION_FIELDS, "id": f"eq.{post_id}"}
        )
        if not rows:
            raise PostNotFound(f"Post {post_id} was not found.")
        return rows[0]

    post = load_post(source, post_id)
    publication = {
        "id": post_id,
        "status": post["status"],
        "approved_draft_id": None,
        "wordpress_post_id": None,
        "published_url": None,
        "published_at": None,
    }
    if published_file(post_id).exists():
        saved = json.loads(published_file(post_id).read_text(encoding="utf-8"))
        publication.update({k: saved.get(k) for k in publication if k != "id"})
    elif post["status"] in GENERATE_FROM and fixture_versions(post_id):
        # POST /drafts never changes the fixture file, so a saved draft
        # stands for the status draft_generated.
        publication["status"] = DRAFT_STATUS
    return publication


def load_latest_draft(source: str, post_id: int) -> dict:
    """The post's latest draft: {"draft_id", "version", "article_text",
    "linkedin_text"}. Raises PostNotReady if the post has no draft.

    draft_id is None for fixture. The reviewer notes are never read here.
    """
    check_source(source)
    if source == "supabase":
        rows = read_rows(
            DRAFTS_TABLE,
            {
                "select": DRAFT_FIELDS,
                "post_id": f"eq.{post_id}",
                "order": "version.desc",
                "limit": "1",
            },
        )
        if not rows:
            raise PostNotReady(f"Post {post_id} has no draft.")
        row = rows[0]
        return {
            "draft_id": row["id"],
            "version": row["version"],
            "article_text": row["article_text"],
            "linkedin_text": row["linkedin_text"],
        }

    versions = fixture_versions(post_id)
    if not versions:
        raise PostNotReady(f"Post {post_id} has no draft.")
    version = max(versions)
    data = json.loads(versions[version].read_text(encoding="utf-8"))
    return {
        "draft_id": None,
        "version": version,
        "article_text": data["article_text"],
        "linkedin_text": data["linkedin_text"],
    }


# -------------------- step 1: request


def request_publish(source: str, post_id: int, version: int) -> dict:
    """Lock the version for publishing: status publish_requested.

    Returns {"draft_id", "version"} of the approved draft. Raises
    PostNotFound, or PostNotReady if the status is not draft_generated or
    the version is not the latest draft. With supabase it happens in one
    transaction, so two calls at the same time cannot both get through.
    """
    check_source(source)
    if source == "supabase":
        rows = call_function(
            REQUEST_FUNCTION,
            {"p_post_id": post_id, "p_version": version},
            migration=PUBLISH_MIGRATION,
        )
        if len(rows) != 1 or "draft_id" not in rows[0] or "version" not in rows[0]:
            raise StoreError(
                f"Unexpected answer from {REQUEST_FUNCTION} for post {post_id}."
            )
        return {"draft_id": rows[0]["draft_id"], "version": rows[0]["version"]}

    publication = load_publication(source, post_id)
    if publication["status"] != PUBLISH_FROM:
        raise PostNotReady(
            f"Post {post_id} cannot be published in status {publication['status']}"
        )
    latest = load_latest_draft(source, post_id)["version"]
    if version != latest:
        raise PostNotReady(
            f"Post {post_id} cannot be published: version {version} "
            f"is not the latest draft (latest is {latest})"
        )
    write_published_file(
        post_id,
        {
            "status": REQUESTED_STATUS,
            "approved_version": version,
            "requested_at": now(),
        },
    )
    return {"draft_id": None, "version": version}


# -------------------- step 2: result


def mark_published(
    source: str, post_id: int, approved: dict, wordpress_post: dict
) -> dict:
    """Save the result: status published, draft, WordPress id and URL, time.

    `approved` is the answer from request_publish and `wordpress_post` the
    answer from WordPress ({"id", "link"}). Returns the saved publication.
    """
    check_source(source)
    if source == "supabase":
        call_function(
            MARK_FUNCTION,
            {
                "p_post_id": post_id,
                "p_draft_id": approved["draft_id"],
                "p_wordpress_post_id": wordpress_post["id"],
                "p_published_url": wordpress_post["link"],
            },
            migration=PUBLISH_MIGRATION,
        )
        return load_publication(source, post_id)

    data = {
        "status": PUBLISHED_STATUS,
        "approved_draft_id": approved["draft_id"],
        "approved_version": approved["version"],
        "wordpress_post_id": wordpress_post["id"],
        "published_url": wordpress_post["link"],
        "published_at": now(),
    }
    write_published_file(post_id, data)
    return load_publication(source, post_id)


def cancel_publish_request(source: str, post_id: int) -> None:
    """Set publish_requested back to draft_generated.

    Only for when WordPress surely did not create the post, so Kisslo can
    press Publicera again.
    """
    check_source(source)
    if source == "supabase":
        call_function(
            CANCEL_FUNCTION, {"p_post_id": post_id}, migration=PUBLISH_MIGRATION
        )
        return
    write_published_file(post_id, {"status": DRAFT_STATUS, "cancelled_at": now()})
