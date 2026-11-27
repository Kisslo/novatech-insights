"""Tests for src/publish_store.py (issue #81). Supabase is never called."""

import io
import json
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlparse

import pytest

import draft_store
import publish_store
from draft_store import PostNotFound, PostNotReady, StoreError
from publish_store import (
    cancel_publish_request,
    load_latest_draft,
    load_publication,
    mark_published,
    request_publish,
)

SUPABASE_KEY = "sb_secret_never_in_messages"
WP_POST = {"id": 42, "link": "https://example.com/?p=42"}


@pytest.fixture(autouse=True)
def fixture_dirs(monkeypatch, tmp_path):
    monkeypatch.setattr(draft_store, "FIXTURE_OUTPUT_DIR", tmp_path / "drafts")
    monkeypatch.setattr(publish_store, "FIXTURE_PUBLISHED_DIR", tmp_path / "published")


def save_fixture_draft(post_id, version, article="# Rubrik\n\nText"):
    folder = draft_store.FIXTURE_OUTPUT_DIR
    folder.mkdir(parents=True, exist_ok=True)
    data = {
        "post_id": post_id,
        "article_text": article,
        "linkedin_text": "Kort. Läs mer: [LÄNK]",
        "reviewer_notes": "secret notes",
        "version": version,
    }
    (folder / f"post_{post_id}_v{version}.json").write_text(
        json.dumps(data), encoding="utf-8"
    )


# -------------------- fixture


def test_fixture_post_without_draft_keeps_its_status():
    publication = load_publication("fixture", 1)
    assert publication["status"] == "angle_received"
    assert publication["wordpress_post_id"] is None


def test_fixture_post_with_draft_counts_as_draft_generated():
    save_fixture_draft(1, 1)
    assert load_publication("fixture", 1)["status"] == "draft_generated"


def test_fixture_unknown_post():
    with pytest.raises(PostNotFound):
        load_publication("fixture", 999)


def test_fixture_latest_draft_has_no_reviewer_notes():
    save_fixture_draft(1, 1, "# Gammal\n\nText")
    save_fixture_draft(1, 2, "# Ny\n\nText")
    draft = load_latest_draft("fixture", 1)
    assert draft == {
        "draft_id": None,
        "version": 2,
        "article_text": "# Ny\n\nText",
        "linkedin_text": "Kort. Läs mer: [LÄNK]",
    }


def test_fixture_no_draft():
    with pytest.raises(PostNotReady, match="has no draft"):
        load_latest_draft("fixture", 1)


def test_fixture_full_flow_request_then_published():
    save_fixture_draft(1, 1)
    approved = request_publish("fixture", 1, 1)
    assert approved == {"draft_id": None, "version": 1}
    assert load_publication("fixture", 1)["status"] == "publish_requested"

    # A second press while WordPress is working is refused.
    with pytest.raises(PostNotReady, match="status publish_requested"):
        request_publish("fixture", 1, 1)

    saved = mark_published("fixture", 1, approved, WP_POST)
    assert saved["status"] == "published"
    assert saved["wordpress_post_id"] == 42
    assert saved["published_url"] == "https://example.com/?p=42"
    assert saved["published_at"]

    with pytest.raises(PostNotReady, match="status published"):
        request_publish("fixture", 1, 1)


def test_fixture_old_version_is_refused():
    save_fixture_draft(1, 1)
    save_fixture_draft(1, 2)
    with pytest.raises(PostNotReady, match="version 1 is not the latest"):
        request_publish("fixture", 1, 1)
    assert load_publication("fixture", 1)["status"] == "draft_generated"


def test_fixture_wrong_status_is_refused():
    with pytest.raises(PostNotReady, match="status approved"):
        request_publish("fixture", 4, 1)


def test_fixture_cancel_allows_a_new_try():
    save_fixture_draft(1, 1)
    request_publish("fixture", 1, 1)
    cancel_publish_request("fixture", 1)
    assert load_publication("fixture", 1)["status"] == "draft_generated"
    assert request_publish("fixture", 1, 1)["version"] == 1


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
        if isinstance(answer, bytes):
            # The raw body, for example b"" for HTTP 204 No Content.
            return io.BytesIO(answer)
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


def test_supabase_load_publication(supabase_env, monkeypatch):
    row = {"id": 7, "status": "published", "wordpress_post_id": 42}
    requests = fake_supabase(monkeypatch, {("GET", "posts"): [row]})
    assert load_publication("supabase", 7) == row
    assert query(requests[0])["id"] == "eq.7"
    assert "wordpress_post_id" in query(requests[0])["select"]


def test_supabase_load_publication_unknown_post(supabase_env, monkeypatch):
    fake_supabase(monkeypatch, {("GET", "posts"): []})
    with pytest.raises(PostNotFound):
        load_publication("supabase", 7)


def test_supabase_latest_draft_reads_newest_without_notes(supabase_env, monkeypatch):
    row = {"id": 55, "version": 3, "article_text": "# A", "linkedin_text": "L"}
    requests = fake_supabase(monkeypatch, {("GET", "post_drafts"): [row]})
    draft = load_latest_draft("supabase", 7)
    assert draft == {
        "draft_id": 55,
        "version": 3,
        "article_text": "# A",
        "linkedin_text": "L",
    }
    params = query(requests[0])
    assert params["order"] == "version.desc"
    assert params["limit"] == "1"
    assert "reviewer_notes" not in params["select"]


def test_supabase_request_publish(supabase_env, monkeypatch):
    requests = fake_supabase(
        monkeypatch, {("POST", "request_publish"): [{"draft_id": 55, "version": 3}]}
    )
    assert request_publish("supabase", 7, 3) == {"draft_id": 55, "version": 3}
    assert body(requests[0]) == {"p_post_id": 7, "p_version": 3}


@pytest.mark.parametrize(
    ("answer", "error", "message"),
    [
        (database_error("Post 7 does not exist"), PostNotFound, "does not exist"),
        (
            database_error("Post 7 cannot be published in status published"),
            PostNotReady,
            "status published",
        ),
        (
            database_error("Post 7 cannot be published: version 2 is not the latest"),
            PostNotReady,
            "not the latest",
        ),
        (HTTPError("u", 404, "Not Found", {}, None), StoreError, "migration 013"),
        ([], StoreError, "Unexpected answer"),
    ],
)
def test_supabase_request_publish_errors(
    supabase_env, monkeypatch, answer, error, message
):
    fake_supabase(monkeypatch, {("POST", "request_publish"): answer})
    with pytest.raises(error, match=message) as raised:
        request_publish("supabase", 7, 3)
    assert SUPABASE_KEY not in str(raised.value)


def test_supabase_mark_published(supabase_env, monkeypatch):
    saved = {"id": 7, "status": "published", "wordpress_post_id": 42}
    requests = fake_supabase(
        monkeypatch,
        {("POST", "mark_post_published"): [], ("GET", "posts"): [saved]},
    )
    result = mark_published("supabase", 7, {"draft_id": 55, "version": 3}, WP_POST)
    assert result == saved
    assert body(requests[0]) == {
        "p_post_id": 7,
        "p_draft_id": 55,
        "p_wordpress_post_id": 42,
        "p_published_url": "https://example.com/?p=42",
    }


def test_supabase_cancel(supabase_env, monkeypatch):
    requests = fake_supabase(monkeypatch, {("POST", "cancel_publish_request"): []})
    cancel_publish_request("supabase", 7)
    assert body(requests[0]) == {"p_post_id": 7}


# PostgREST answers HTTP 204 with an empty body for a function that returns
# void. The database has already done the work, so it must not become a
# StoreError (that gave 502 after a successful publish, found when testing
# migration 013 with PostgREST 12.2.3).
NO_CONTENT = b""


def test_supabase_mark_published_with_empty_answer(supabase_env, monkeypatch):
    saved = {"id": 7, "status": "published", "wordpress_post_id": 42}
    fake_supabase(
        monkeypatch,
        {("POST", "mark_post_published"): NO_CONTENT, ("GET", "posts"): [saved]},
    )
    result = mark_published("supabase", 7, {"draft_id": 55, "version": 3}, WP_POST)
    assert result == saved


def test_supabase_cancel_with_empty_answer(supabase_env, monkeypatch):
    requests = fake_supabase(
        monkeypatch, {("POST", "cancel_publish_request"): NO_CONTENT}
    )
    cancel_publish_request("supabase", 7)
    assert body(requests[0]) == {"p_post_id": 7}


@pytest.mark.parametrize("answer", [NO_CONTENT, b"  \n", b"null"])
def test_call_function_treats_void_answer_as_no_rows(supabase_env, monkeypatch, answer):
    fake_supabase(monkeypatch, {("POST", "cancel_publish_request"): answer})
    assert draft_store.call_function("cancel_publish_request", {"p_post_id": 7}) == []


def test_supabase_request_publish_with_empty_answer_is_an_error(
    supabase_env, monkeypatch
):
    """request_publish must return a row; an empty answer is not a success."""
    fake_supabase(monkeypatch, {("POST", "request_publish"): NO_CONTENT})
    with pytest.raises(StoreError, match="Unexpected answer"):
        request_publish("supabase", 7, 3)


def test_call_function_still_refuses_other_non_json(supabase_env, monkeypatch):
    fake_supabase(monkeypatch, {("POST", "cancel_publish_request"): b"<html>"})
    with pytest.raises(StoreError, match="did not answer with JSON"):
        draft_store.call_function("cancel_publish_request", {"p_post_id": 7})
