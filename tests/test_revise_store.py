"""Tests for src/revise_store.py (issue #67). Supabase is never called."""

import io
import json
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlparse

import pytest

import draft_store
import publish_store
from draft_store import PostNotFound, PostNotReady, StoreError
from publish_store import load_publication, request_publish
from revise_store import (
    add_change_request_to_notes,
    keep,
    load_draft_for_revision,
    load_post_state,
    request_changes,
    save_revision,
    topic_with_sources,
)

SUPABASE_KEY = "sb_secret_never_in_messages"


@pytest.fixture(autouse=True)
def fixture_dirs(monkeypatch, tmp_path):
    monkeypatch.setattr(draft_store, "FIXTURE_OUTPUT_DIR", tmp_path / "drafts")
    monkeypatch.setattr(publish_store, "FIXTURE_PUBLISHED_DIR", tmp_path / "published")


def save_fixture_draft(post_id, version):
    folder = draft_store.FIXTURE_OUTPUT_DIR
    folder.mkdir(parents=True, exist_ok=True)
    data = {
        "post_id": post_id,
        "article_text": f"# Rubrik v{version}\n\nText",
        "linkedin_text": "Kort. Läs mer: [LÄNK]",
        "reviewer_notes": "notes",
        "source_news_ids": [11, 12],
        "stance": "rebut",
        "version": version,
    }
    (folder / f"post_{post_id}_v{version}.json").write_text(
        json.dumps(data), encoding="utf-8"
    )


ROW = {
    "post_id": 1,
    "article_text": "# Ny\n\nText",
    "linkedin_text": "Ny. Läs mer: [LÄNK]",
    "reviewer_notes": "notes",
    "source_news_ids": [11],
    "stance": "rebut",
}


# -------------------- helpers


def test_topic_with_sources_keeps_only_the_drafts_sources_in_their_order():
    topic = {
        "id": 7,
        "articles": [{"news_id": 11}, {"news_id": 12}, {"news_id": 13}],
    }
    result = topic_with_sources(topic, [13, 11])
    assert [a["news_id"] for a in result["articles"]] == [13, 11]
    assert len(topic["articles"]) == 3  # the input is not changed


def test_topic_with_sources_refuses_when_no_source_is_left():
    with pytest.raises(PostNotReady, match="no longer in topic 7"):
        topic_with_sources({"id": 7, "articles": [{"news_id": 11}]}, [99])


def test_add_change_request_to_notes():
    notes = add_change_request_to_notes("# Notes\n", "  Kortare ingress. ", 2)
    assert notes == (
        "# Notes\n\n## Change request (on version 2)\n\nKortare ingress.\n"
    )


# -------------------- fixture


def test_fixture_draft_for_revision_is_the_latest_with_stance_and_sources():
    save_fixture_draft(1, 1)
    save_fixture_draft(1, 2)
    draft = load_draft_for_revision("fixture", 1)
    assert draft["version"] == 2
    assert draft["article_text"].startswith("# Rubrik v2")
    assert draft["stance"] == "rebut"
    assert draft["source_news_ids"] == [11, 12]
    assert draft["change_request"] is None


def test_fixture_no_draft_for_revision():
    with pytest.raises(PostNotReady, match="has no draft"):
        load_draft_for_revision("fixture", 1)


def test_fixture_keep_sets_draft_kept_and_blocks_publishing():
    save_fixture_draft(1, 1)
    assert keep("fixture", 1, 1) == {"draft_id": None, "version": 1}
    assert load_post_state("fixture", 1)["status"] == "draft_kept"
    with pytest.raises(PostNotReady, match="cannot be published in status"):
        request_publish("fixture", 1, 1)


def test_fixture_keep_twice_is_refused():
    save_fixture_draft(1, 1)
    keep("fixture", 1, 1)
    with pytest.raises(PostNotReady, match="cannot be kept in status draft_kept"):
        keep("fixture", 1, 1)


def test_fixture_keep_old_version_is_refused():
    save_fixture_draft(1, 1)
    save_fixture_draft(1, 2)
    with pytest.raises(PostNotReady, match="version 1 is not the latest"):
        keep("fixture", 1, 1)


def test_fixture_keep_after_failed_change_is_allowed():
    # Ändra was pressed but no new version was saved (Claude failed): Skippa
    # still works (migration 015), Publicera does not.
    save_fixture_draft(1, 1)
    request_changes("fixture", 1, 1, "Kortare.")
    with pytest.raises(PostNotReady, match="cannot be published in status"):
        request_publish("fixture", 1, 1)
    assert keep("fixture", 1, 1)["version"] == 1
    assert load_post_state("fixture", 1)["status"] == "draft_kept"


def test_fixture_keep_after_failed_change_old_version_is_refused():
    save_fixture_draft(1, 1)
    save_fixture_draft(1, 2)
    request_changes("fixture", 1, 2, "Kortare.")
    with pytest.raises(PostNotReady, match="version 1 is not the latest"):
        keep("fixture", 1, 1)


def test_fixture_keep_unknown_post():
    with pytest.raises(PostNotFound):
        keep("fixture", 999, 1)


def test_fixture_full_flow_change_then_new_version_then_keep():
    save_fixture_draft(1, 1)
    assert request_changes("fixture", 1, 1, "Kortare.")["version"] == 1
    assert load_post_state("fixture", 1)["status"] == "changes_requested"
    assert load_draft_for_revision("fixture", 1)["change_request"] == "Kortare."
    # A second press on the same version is refused, like in 014.
    with pytest.raises(PostNotReady, match="cannot receive changes in status"):
        request_changes("fixture", 1, 1, "Kortare.")

    post = load_post_state("fixture", 1)
    saved = save_revision("fixture", post, ROW)
    assert saved["version"] == 2
    assert load_post_state("fixture", 1)["status"] == "draft_generated"
    assert keep("fixture", 1, 2)["version"] == 2


def test_fixture_empty_change_request_is_refused():
    save_fixture_draft(1, 1)
    with pytest.raises(PostNotReady, match="change request is empty"):
        request_changes("fixture", 1, 1, "  ")
    assert load_publication("fixture", 1)["status"] == "draft_generated"


# -------------------- supabase


@pytest.fixture
def supabase_env(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://test.supabase.co/")
    monkeypatch.setenv("SUPABASE_KEY", SUPABASE_KEY)


def fake_supabase(monkeypatch, answers):
    """Replace urlopen. `answers` maps (method, table) to JSON or an exception."""
    requests = []

    def call(request, timeout):
        requests.append(request)
        table = urlparse(request.full_url).path.rsplit("/", 1)[-1]
        answer = answers[(request.get_method(), table)]
        if isinstance(answer, Exception):
            raise answer
        return io.BytesIO(json.dumps(answer).encode("utf-8"))

    monkeypatch.setattr("draft_store.urlopen", call)
    monkeypatch.setattr("label_topics.urlopen", call)
    return requests


def query(request):
    return {k: v[0] for k, v in parse_qs(urlparse(request.full_url).query).items()}


def body(request):
    return json.loads(request.data.decode("utf-8"))


def database_error(message):
    data = json.dumps({"code": "P0001", "message": message}).encode("utf-8")
    return HTTPError("u", 400, "Bad Request", {}, io.BytesIO(data))


def test_supabase_draft_for_revision(supabase_env, monkeypatch):
    row = {
        "id": 55,
        "version": 3,
        "article_text": "# A",
        "linkedin_text": "L",
        "stance": "agree",
        "source_news_ids": [11],
        "change_request": None,
    }
    requests = fake_supabase(monkeypatch, {("GET", "post_drafts"): [row]})
    draft = load_draft_for_revision("supabase", 7)
    assert draft["draft_id"] == 55 and draft["version"] == 3
    assert draft["source_news_ids"] == [11]
    params = query(requests[0])
    assert params["post_id"] == "eq.7"
    assert params["order"] == "version.desc"
    assert "reviewer_notes" not in params["select"]


def test_supabase_post_state_is_the_posts_row(supabase_env, monkeypatch):
    row = {"id": 7, "topic_id": 101, "status": "changes_requested"}
    fake_supabase(monkeypatch, {("GET", "posts"): [row]})
    assert load_post_state("supabase", 7)["status"] == "changes_requested"


def test_supabase_keep(supabase_env, monkeypatch):
    requests = fake_supabase(
        monkeypatch, {("POST", "keep_draft"): [{"draft_id": 55, "version": 3}]}
    )
    assert keep("supabase", 7, 3) == {"draft_id": 55, "version": 3}
    assert body(requests[0]) == {"p_post_id": 7, "p_version": 3}


def test_supabase_request_changes(supabase_env, monkeypatch):
    requests = fake_supabase(
        monkeypatch,
        {("POST", "request_draft_changes"): [{"draft_id": 55, "version": 3}]},
    )
    assert request_changes("supabase", 7, 3, "Kortare.") == {
        "draft_id": 55,
        "version": 3,
    }
    assert body(requests[0]) == {
        "p_post_id": 7,
        "p_version": 3,
        "p_change_request": "Kortare.",
    }


@pytest.mark.parametrize(
    ("answer", "error", "message"),
    [
        (database_error("Post 7 does not exist"), PostNotFound, "does not exist"),
        (
            database_error("Post 7 cannot be kept in status draft_kept"),
            PostNotReady,
            "status draft_kept",
        ),
        (
            database_error("Post 7 cannot be kept: version 2 is not the latest draft"),
            PostNotReady,
            "not the latest",
        ),
        (HTTPError("u", 404, "Not Found", {}, None), StoreError, "migration 014"),
        ([], StoreError, "Unexpected answer"),
    ],
)
def test_supabase_keep_errors(supabase_env, monkeypatch, answer, error, message):
    fake_supabase(monkeypatch, {("POST", "keep_draft"): answer})
    with pytest.raises(error, match=message) as raised:
        keep("supabase", 7, 3)
    assert SUPABASE_KEY not in str(raised.value)


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("Post 7 cannot receive changes in status draft_kept", "status draft_kept"),
        (
            "Post 7 cannot receive changes: version 2 is not the latest draft",
            "not the latest",
        ),
        ("Post 7 cannot receive changes: the change request is empty", "empty"),
    ],
)
def test_supabase_request_changes_refused(supabase_env, monkeypatch, message, expected):
    fake_supabase(
        monkeypatch, {("POST", "request_draft_changes"): database_error(message)}
    )
    with pytest.raises(PostNotReady, match=expected):
        request_changes("supabase", 7, 3, "Kortare.")
