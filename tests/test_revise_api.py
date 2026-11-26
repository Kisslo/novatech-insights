"""Tests for POST /drafts/{post_id}/revise and /keep (issue #67).

Claude and Supabase are never called: the fixture source is used, and
call_claude is replaced.
"""

import json

import pytest
from fastapi.testclient import TestClient

import draft_api
import draft_store
import publish_store
import revise_api
from content_tools import ClaudeError
from draft_article import REVIEW_SYSTEM_PROMPT, REVISE_SYSTEM_PROMPT
from draft_store import StoreError
from telegram_api import app

API_KEY = "test-key-that-is-long-enough-for-revise-12345"
CHANGE = "Gör ingressen kortare och nämn föreningar."
client = TestClient(app)

ARTICLE = "\n".join(
    [
        "# AI-regler: börja nu",
        "",
        "Ingressen säger det viktigaste.",
        "",
        "## Avsnitt 1",
        "",
        "ord " * 200,
        "",
        "## Avsnitt 2",
        "",
        "ord " * 200,
        "",
        "## Novatechs råd",
        "",
        "ord " * 200,
        "",
        "## Källor",
        "- Example Tech News: EU guidance – "
        "https://example.com/tech/eu-ai-act-guidance-small-business",
    ]
)
REVISED = ARTICLE.replace("Ingressen säger det viktigaste.", "Kort ingress.")
LINKEDIN = "Första meningen. Andra meningen. Tredje meningen. Läs mer: [LÄNK]"


def answer(notes_tag, notes, article=ARTICLE):
    return (
        f"<article_draft>\n{article}\n</article_draft>\n"
        f"<linkedin_post>\n{LINKEDIN}\n</linkedin_post>\n"
        f"<{notes_tag}>\n{notes}\n</{notes_tag}>"
    )


@pytest.fixture(autouse=True)
def api_env(monkeypatch, tmp_path):
    monkeypatch.setenv("TELEGRAM_API_KEY", API_KEY)
    monkeypatch.setenv("TELEGRAM_SOURCE", "fixture")
    monkeypatch.delenv("CONTENT_WRITER_MODEL", raising=False)
    monkeypatch.delenv("CONTENT_WRITER_EFFORT", raising=False)
    monkeypatch.setattr(draft_store, "FIXTURE_OUTPUT_DIR", tmp_path / "drafts")
    monkeypatch.setattr(publish_store, "FIXTURE_PUBLISHED_DIR", tmp_path / "published")
    draft_api._in_progress.clear()


@pytest.fixture
def claude(monkeypatch):
    """Replace call_claude in /revise. Returns the list of calls made."""
    calls = []

    def call(model, system_prompt, prompt, effort, max_tokens):
        calls.append((system_prompt, prompt))
        if system_prompt == REVIEW_SYSTEM_PROMPT:
            return answer("review_notes", "- Strök en floskel.", REVISED), 500, 1000
        return answer("reviewer_notes", "- Kortade ingressen.", REVISED), 1000, 2000

    monkeypatch.setattr(revise_api, "call_claude", call)
    return calls


def save_draft(post_id=1, version=1, stance="rebut", news_ids=(1001, 1002)):
    """A saved fixture draft, as POST /drafts writes it."""
    folder = draft_store.FIXTURE_OUTPUT_DIR
    folder.mkdir(parents=True, exist_ok=True)
    data = {
        "post_id": post_id,
        "article_text": ARTICLE,
        "linkedin_text": LINKEDIN,
        "reviewer_notes": "notes",
        "source_news_ids": list(news_ids),
        "stance": stance,
        "version": version,
        "status": "draft_generated",
    }
    (folder / f"post_{post_id}_v{version}.json").write_text(
        json.dumps(data, ensure_ascii=False), encoding="utf-8"
    )


def state(tmp_path, post_id=1):
    path = tmp_path / "published" / f"post_{post_id}.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def post_revise(post_id=1, body=None, key=API_KEY, dry_run=False):
    body = {"version": 1, "change_request": CHANGE} if body is None else body
    headers = {"X-API-Key": key} if key is not None else {}
    url = f"/drafts/{post_id}/revise" + ("?dry_run=true" if dry_run else "")
    return client.post(url, headers=headers, json=body)


def post_keep(post_id=1, body=None, key=API_KEY):
    body = {"version": 1} if body is None else body
    headers = {"X-API-Key": key} if key is not None else {}
    return client.post(f"/drafts/{post_id}/keep", headers=headers, json=body)


# -------------------- access and body


@pytest.mark.parametrize("key", [None, "wrong-key"])
def test_both_endpoints_require_api_key(claude, key):
    save_draft()
    assert post_revise(key=key).status_code == 401
    assert post_keep(key=key).status_code == 401
    assert claude == []


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"version": 1},
        {"version": 0, "change_request": CHANGE},
        {"version": 1, "change_request": "   "},
        {"version": 1, "change_request": "x" * 2001},
        {"version": 1, "feedback": CHANGE},
    ],
)
def test_invalid_revise_body_gives_422(claude, body):
    save_draft()
    assert post_revise(body=body).status_code == 422
    assert claude == []


@pytest.mark.parametrize("body", [{}, {"version": 0}, {"version": 1, "x": 1}])
def test_invalid_keep_body_gives_422(body):
    save_draft()
    assert post_keep(body=body).status_code == 422


def test_unknown_post_gives_404(claude):
    assert post_revise(post_id=999).status_code == 404
    assert post_keep(post_id=999).status_code == 404


def test_invalid_source_gives_500(claude, monkeypatch):
    monkeypatch.setenv("TELEGRAM_SOURCE", "excel")
    assert post_revise().status_code == 500
    assert post_keep().status_code == 500


# -------------------- Skippa


def test_keep_sets_draft_kept_and_returns_a_message(tmp_path):
    save_draft()
    response = post_keep()
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "draft_kept"
    assert data["version"] == 1
    assert data["messages"][0]["text"].startswith("<b>Utkastet är sparat (v1)</b>")
    assert data["messages"][0]["parse_mode"] == "HTML"
    assert state(tmp_path)["status"] == "draft_kept"


def test_keep_twice_or_old_version_gives_409():
    save_draft(version=1)
    save_draft(version=2)
    assert "not the latest" in post_keep(body={"version": 1}).json()["detail"]
    assert post_keep(body={"version": 2}).status_code == 200
    assert post_keep(body={"version": 2}).status_code == 409


def test_keep_without_draft_gives_409():
    assert post_keep().status_code == 409  # post 1 has no draft yet


def test_keep_supabase_failure_gives_502_without_details(monkeypatch):
    def broken(*args):
        raise StoreError("secret details from Supabase")

    monkeypatch.setattr(revise_api, "keep", broken)
    response = post_keep()
    assert response.status_code == 502
    assert "secret" not in response.text


# -------------------- Ändra


def test_revise_writes_the_next_version_from_the_previous_one(claude, tmp_path):
    save_draft()
    response = post_revise()
    assert response.status_code == 200
    data = response.json()
    assert data["based_on_version"] == 1
    assert data["version"] == 2
    assert data["status"] == "draft_generated"
    assert data["stance"] == "rebut"  # kept from version 1
    assert data["reviewed"] is True

    # Call 1 revises the previous text, call 2 reviews it.
    assert [system for system, _ in claude] == [
        REVISE_SYSTEM_PROMPT,
        REVIEW_SYSTEM_PROMPT,
    ]
    prompt = claude[0][1]
    assert CHANGE in prompt and "<previous_article>" in prompt
    # Only the sources of version 1 (1001, 1002), not 1003 of the topic.
    assert '<source id="1001">' in prompt and '<source id="1002">' in prompt
    assert '<source id="1003">' not in prompt

    # The change request is saved on v1, v2 is saved, the status is back.
    v1 = json.loads((tmp_path / "drafts" / "post_1_v1.json").read_text("utf-8"))
    assert v1["change_request"] == CHANGE
    v2 = json.loads((tmp_path / "drafts" / "post_1_v2.json").read_text("utf-8"))
    assert "Kort ingress." in v2["article_text"]
    assert v2["source_news_ids"] == [1001, 1002]
    assert "## Change request (on version 1)" in v2["reviewer_notes"]
    assert CHANGE in v2["reviewer_notes"]
    assert state(tmp_path)["status"] == "draft_generated"


def test_revise_messages_have_new_buttons(claude):
    save_draft()
    messages = post_revise().json()["messages"]
    assert messages[0]["text"].startswith("<b>Utkast v2 · Artikel")
    buttons = messages[-1]["buttons"]
    assert [b["callback_data"] for b in buttons] == [
        "publish:1:2",
        "revise:1:2",
        "keep:1:2",
    ]
    assert any("Change request (on version 1)" in m["text"] for m in messages)


def test_revise_then_revise_again_then_keep(claude):
    save_draft()
    assert post_revise().json()["version"] == 2
    body = {"version": 2, "change_request": "Ännu kortare."}
    assert post_revise(body=body).json()["version"] == 3
    assert post_keep(body={"version": 3}).json()["status"] == "draft_kept"
    assert post_revise(body={"version": 3, "change_request": "x"}).status_code == 409


def test_old_version_gives_409_and_calls_nothing(claude, tmp_path):
    save_draft(version=1)
    save_draft(version=2)
    response = post_revise()
    assert response.status_code == 409
    assert "latest is 2" in response.json()["detail"]
    assert claude == []
    assert state(tmp_path) is None


@pytest.mark.parametrize("post_id", [1, 2])
def test_post_without_draft_gives_409(claude, post_id):
    # Post 1 is angle_received and post 2 awaiting_angle, both without a draft.
    assert post_revise(post_id=post_id).status_code == 409
    assert claude == []


def test_kept_post_cannot_be_revised(claude):
    save_draft()
    post_keep()
    response = post_revise()
    assert response.status_code == 409
    assert "draft_kept" in response.json()["detail"]


def test_sources_gone_from_topic_gives_409(claude):
    save_draft(news_ids=(9999,))
    response = post_revise()
    assert response.status_code == 409
    assert "no longer in topic" in response.json()["detail"]
    assert claude == []


def test_dry_run_calls_nothing_and_changes_nothing(claude, tmp_path):
    save_draft()
    response = post_revise(dry_run=True)
    assert response.status_code == 200
    data = response.json()
    assert data["dry_run"] is True
    assert data["based_on_version"] == 1
    assert CHANGE in data["prompt"]
    assert data["estimate"]["max_output_tokens"] > 0
    assert claude == []
    assert state(tmp_path) is None
    assert sorted(p.name for p in (tmp_path / "drafts").iterdir()) == ["post_1_v1.json"]


def test_claude_failure_leaves_changes_requested_and_a_retry_works(
    monkeypatch, tmp_path, claude
):
    save_draft()
    real_call = revise_api.call_claude

    def failing(*args):
        raise ClaudeError("Claude is overloaded")

    monkeypatch.setattr(revise_api, "call_claude", failing)
    response = post_revise()
    assert response.status_code == 502
    assert "overloaded" not in response.text
    assert state(tmp_path)["status"] == "changes_requested"
    assert not (tmp_path / "drafts" / "post_1_v2.json").exists()

    # A new press on the same version skips request_changes and writes v2.
    monkeypatch.setattr(revise_api, "call_claude", real_call)
    retry = post_revise(body={"version": 1, "change_request": "Kortare, tack."})
    assert retry.status_code == 200
    assert retry.json()["version"] == 2
    assert "Kortare, tack." in retry.json()["reviewer_notes"]
    assert state(tmp_path)["status"] == "draft_generated"


def test_save_failure_gives_502_without_details(claude, monkeypatch):
    save_draft()

    def broken(*args):
        raise StoreError("secret details from Supabase")

    monkeypatch.setattr(revise_api, "save_revision", broken)
    response = post_revise()
    assert response.status_code == 502
    assert "secret" not in response.text


def test_missing_drafts_table_gives_502_before_claude_is_called(claude, monkeypatch):
    save_draft()

    def broken(source):
        raise StoreError("post_drafts is missing")

    monkeypatch.setattr(revise_api, "check_can_save", broken)
    assert post_revise().status_code == 502
    assert claude == []


def test_draft_already_being_written_gives_409(claude):
    save_draft()
    draft_api._in_progress.add(1)  # for example POST /drafts at the same time
    response = post_revise()
    assert response.status_code == 409
    assert "already being written" in response.json()["detail"]
    assert claude == []
