"""Read and store Kisslo's Ändra and Skippa on a draft (issue #67).

Used by the endpoints in revise_api.py:
    POST /drafts/{post_id}/keep      Skippa: keep(source, post_id, version)
    POST /drafts/{post_id}/revise    Ändra:
        post = load_post_state(source, post_id)
        draft = load_draft_for_revision(source, post_id)
        topic = topic_with_sources(load_topic(...), draft["source_news_ids"])
        request_changes(source, post_id, version, change_request)
        ... revise_draft() in draft_article.py ...
        save_revision(source, post, row)

Both buttons only work on the latest draft of a post in draft_generated.
keep sets draft_kept; nothing is published and the draft stays. Ändra saves
the change request on the version Kisslo read and sets changes_requested;
save_post_draft then accepts the next version and sets draft_generated.

If writing the new version fails after request_changes, the post stays in
changes_requested. A new /revise for the same version then skips
request_changes and writes the version (decided for #67).

Two sources, the same as TELEGRAM_SOURCE:
    fixture   drafts from output/drafts/ and the post's state in
              output/published/post_<id>.json, the same file that
              publish_store.py reads, so a kept fixture post cannot be
              published either. The fixture posts file is never changed.
    supabase  the posts and post_drafts tables, and the database functions
              keep_draft and request_draft_changes (migration 014, Nosheen).
"""

import json

from draft_store import (
    DRAFT_STATUS,
    DRAFTS_TABLE,
    PostNotReady,
    StoreError,
    call_function,
    check_source,
    load_post,
    read_rows,
    save_version,
)
from publish_store import (
    fixture_versions,
    load_publication,
    now,
    published_file,
    write_published_file,
)

REVISE_MIGRATION = "014"
KEEP_FUNCTION = "keep_draft"
CHANGES_FUNCTION = "request_draft_changes"

KEPT_STATUS = "draft_kept"
CHANGES_STATUS = "changes_requested"
BUTTONS_FROM = DRAFT_STATUS  # both buttons need a draft that waits for Kisslo

REVISION_FIELDS = (
    "id,version,article_text,linkedin_text,stance,source_news_ids,change_request"
)


# -------------------- reading


def load_post_state(source: str, post_id: int) -> dict:
    """The post with its current status: {"id", "topic_id", "status", "kisslo_angle"}.

    For fixture the status comes from the state file and the saved drafts
    (as in publish_store.load_publication), since the posts file never
    changes. Raises PostNotFound if there is no such post.
    """
    post = load_post(source, post_id)
    if source == "fixture":
        post = {**post, "status": load_publication(source, post_id)["status"]}
    return post


def load_draft_for_revision(source: str, post_id: int) -> dict:
    """The post's latest draft with what a revision needs.

    Returns {"draft_id", "version", "article_text", "linkedin_text",
    "stance", "source_news_ids", "change_request"}. draft_id is None for
    fixture. Raises PostNotReady if the post has no draft.
    """
    check_source(source)
    if source == "supabase":
        rows = read_rows(
            DRAFTS_TABLE,
            {
                "select": REVISION_FIELDS,
                "post_id": f"eq.{post_id}",
                "order": "version.desc",
                "limit": "1",
            },
        )
        if not rows:
            raise PostNotReady(f"Post {post_id} has no draft.")
        row = rows[0]
        draft_id = row["id"]
    else:
        versions = fixture_versions(post_id)
        if not versions:
            raise PostNotReady(f"Post {post_id} has no draft.")
        row = json.loads(versions[max(versions)].read_text(encoding="utf-8"))
        row["version"] = max(versions)
        draft_id = None
    return {
        "draft_id": draft_id,
        "version": row["version"],
        "article_text": row.get("article_text") or "",
        "linkedin_text": row.get("linkedin_text") or "",
        "stance": row.get("stance"),
        "source_news_ids": row.get("source_news_ids") or [],
        "change_request": row.get("change_request"),
    }


def topic_with_sources(topic: dict, news_ids: list[int]) -> dict:
    """The topic with only the articles the earlier version used, in its order.

    A revision may not bring in new sources (#67), even if the topic has
    got more articles since. Raises PostNotReady if none of them is left.
    """
    by_id = {int(article["news_id"]): article for article in topic["articles"]}
    articles = [by_id[int(i)] for i in news_ids if int(i) in by_id]
    if not articles:
        raise PostNotReady(
            f"Post cannot be revised: the sources of the draft are no longer "
            f"in topic {topic.get('id')}."
        )
    return {**topic, "articles": articles}


# -------------------- fixture checks


def check_fixture_button(post_id: int, version: int, action: str) -> None:
    """The same checks as keep_draft and request_draft_changes in 014.

    The messages follow 014, so fixture and supabase give the same answers.
    """
    status = load_publication("fixture", post_id)["status"]
    if status != BUTTONS_FROM:
        raise PostNotReady(f"Post {post_id} cannot {action} in status {status}")
    versions = fixture_versions(post_id)
    if not versions or version != max(versions):
        raise PostNotReady(
            f"Post {post_id} cannot {action}: version {version} is not the latest draft"
        )


def function_answer(rows: list[dict], name: str, post_id: int) -> dict:
    """The one row {"draft_id", "version"} that the 014 functions return."""
    if len(rows) != 1 or "draft_id" not in rows[0] or "version" not in rows[0]:
        raise StoreError(f"Unexpected answer from {name} for post {post_id}.")
    return {"draft_id": rows[0]["draft_id"], "version": rows[0]["version"]}


# -------------------- Skippa


def keep(source: str, post_id: int, version: int) -> dict:
    """Skippa: set draft_kept. Returns {"draft_id", "version"} of the kept draft.

    Raises PostNotFound, or PostNotReady if the status is not
    draft_generated or the version is not the latest draft.
    """
    check_source(source)
    if source == "supabase":
        rows = call_function(
            KEEP_FUNCTION,
            {"p_post_id": post_id, "p_version": version},
            migration=REVISE_MIGRATION,
        )
        return function_answer(rows, KEEP_FUNCTION, post_id)

    load_post(source, post_id)  # PostNotFound
    check_fixture_button(post_id, version, "be kept")
    write_published_file(
        post_id, {"status": KEPT_STATUS, "kept_version": version, "kept_at": now()}
    )
    return {"draft_id": None, "version": version}


# -------------------- Ändra


def request_changes(
    source: str, post_id: int, version: int, change_request: str
) -> dict:
    """Ändra: save the change request on the version and set changes_requested.

    Returns {"draft_id", "version"} of the version Kisslo read. Raises
    PostNotFound, or PostNotReady if the status is not draft_generated, the
    version is not the latest draft or the text is empty.
    """
    check_source(source)
    if source == "supabase":
        rows = call_function(
            CHANGES_FUNCTION,
            {
                "p_post_id": post_id,
                "p_version": version,
                "p_change_request": change_request,
            },
            migration=REVISE_MIGRATION,
        )
        return function_answer(rows, CHANGES_FUNCTION, post_id)

    load_post(source, post_id)  # PostNotFound
    check_fixture_button(post_id, version, "receive changes")
    if not change_request.strip():
        raise PostNotReady(
            f"Post {post_id} cannot receive changes: the change request is empty"
        )
    path = fixture_versions(post_id)[version]
    data = json.loads(path.read_text(encoding="utf-8"))
    data["change_request"] = change_request
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    write_published_file(
        post_id,
        {"status": CHANGES_STATUS, "changes_version": version, "requested_at": now()},
    )
    return {"draft_id": None, "version": version}


def save_revision(source: str, post: dict, row: dict) -> dict:
    """Save the new version (save_post_draft) and set draft_generated.

    The same as draft_store.save_version. For fixture the state file is
    also set back to draft_generated, so the new version can get buttons.
    """
    saved = save_version(source, post, row)
    if source == "fixture" and published_file(post["id"]).exists():
        write_published_file(post["id"], {"status": DRAFT_STATUS, "revised_at": now()})
    return saved


def add_change_request_to_notes(
    notes: str, change_request: str, based_on_version: int
) -> str:
    """The reviewer notes with the change request the new version was built on.

    The request is also saved on the earlier version (014), but here it is
    clear which request each version answers, also after a retry.
    """
    return (
        f"{notes.rstrip()}\n\n"
        f"## Change request (on version {based_on_version})\n\n"
        f"{change_request.strip()}\n"
    )
