"""Tests for POST /drafts/{post_id}/publish (issue #81).

WordPress and Supabase are never called: the fixture source is used, and
create_post (or urlopen) is replaced.
"""

import io
import json
from urllib.error import HTTPError, URLError

import pytest
from fastapi.testclient import TestClient

import draft_store
import publish_api
import publish_store
import wordpress_publish
from draft_store import StoreError
from telegram_api import app

API_KEY = "test-key-that-is-long-enough-for-the-check-123"
PASSWORD = "abcd efgh ijkl mnop qrst uvwx"
NOTES = "SECRET reviewer notes that must never be published"
client = TestClient(app)

ARTICLE = "\n".join(
    [
        "# AI-regler: börja nu",
        "",
        "Ingressen säger det viktigaste.",
        "",
        "## Avsnitt",
        "",
        "Text med en <tagg> & mer.",
        "",
        "## Källor",
        "- Example: Guide – https://example.com/guide",
    ]
)
LINKEDIN = "Första meningen. Andra meningen. Läs mer: [LÄNK]"
WP_ANSWER = {"id": 42, "link": "https://wp.example.com/?p=42", "status": "draft"}


@pytest.fixture(autouse=True)
def api_env(monkeypatch, tmp_path):
    monkeypatch.setenv("TELEGRAM_API_KEY", API_KEY)
    monkeypatch.setenv("TELEGRAM_SOURCE", "fixture")
    monkeypatch.setenv("WORDPRESS_URL", "https://wp.example.com")
    monkeypatch.setenv("WORDPRESS_USER", "bot")
    monkeypatch.setenv("WORDPRESS_APP_PASSWORD", PASSWORD)
    monkeypatch.delenv("WORDPRESS_POST_STATUS", raising=False)
    monkeypatch.delenv("WORDPRESS_CATEGORY_ID", raising=False)
    monkeypatch.setattr(draft_store, "FIXTURE_OUTPUT_DIR", tmp_path / "drafts")
    monkeypatch.setattr(publish_store, "FIXTURE_PUBLISHED_DIR", tmp_path / "published")
    publish_api._in_progress.clear()


@pytest.fixture
def wordpress(monkeypatch):
    """Replace create_post. Returns the list of payloads sent."""
    sent = []

    def fake_create_post(settings, payload):
        sent.append(payload)
        return {**WP_ANSWER, "status": payload["status"]}

    monkeypatch.setattr(publish_api, "create_post", fake_create_post)
    return sent


def save_draft(post_id=1, version=1, article=ARTICLE, linkedin=LINKEDIN):
    folder = draft_store.FIXTURE_OUTPUT_DIR
    folder.mkdir(parents=True, exist_ok=True)
    data = {
        "post_id": post_id,
        "article_text": article,
        "linkedin_text": linkedin,
        "reviewer_notes": NOTES,
        "version": version,
        "status": "draft_generated",
    }
    (folder / f"post_{post_id}_v{version}.json").write_text(
        json.dumps(data, ensure_ascii=False), encoding="utf-8"
    )


def publish(post_id=1, body=None, key=API_KEY, dry_run=False):
    headers = {"X-API-Key": key} if key is not None else {}
    url = f"/drafts/{post_id}/publish" + ("?dry_run=true" if dry_run else "")
    return client.post(
        url, headers=headers, json={"version": 1} if body is None else body
    )


def status(post_id=1):
    return publish_store.load_publication("fixture", post_id)["status"]


# -------------------- success


def test_publish_creates_wordpress_draft_and_returns_messages(wordpress):
    save_draft()
    response = publish()

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "published"
    assert data["version"] == 1
    assert data["wordpress_post_id"] == 42
    assert data["wordpress_status"] == "draft"
    assert data["url"] == "https://wp.example.com/?p=42"
    assert data["edit_url"] == (
        "https://wp.example.com/wp-admin/post.php?post=42&action=edit"
    )
    assert data["published_at"]
    assert data["linkedin"] == (
        "Första meningen. Andra meningen. Läs mer: https://wp.example.com/?p=42"
    )
    assert "[LÄNK]" not in json.dumps(data["messages"], ensure_ascii=False)
    assert "Utkast i WordPress v1: AI-regler: börja nu" in data["messages"][0]["text"]
    assert "post=42&amp;action=edit" in data["messages"][0]["text"]
    assert data["messages"][1]["text"].startswith("<b>LinkedIn-inlägg att posta</b>")
    assert len(wordpress) == 1
    assert wordpress[0]["status"] == "draft"
    assert wordpress[0]["title"] == "AI-regler: börja nu"
    assert status() == "published"


def test_publish_status_from_env(wordpress, monkeypatch):
    monkeypatch.setenv("WORDPRESS_POST_STATUS", "publish")
    monkeypatch.setenv("WORDPRESS_CATEGORY_ID", "5")
    save_draft()
    response = publish()

    assert response.status_code == 200
    assert wordpress[0]["status"] == "publish"
    assert wordpress[0]["categories"] == [5]
    assert "Publicerad v1" in response.json()["messages"][0]["text"]


def test_second_call_creates_no_new_post(wordpress):
    save_draft()
    assert publish().status_code == 200

    response = publish()

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert "already published: https://wp.example.com/?p=42" in detail
    assert len(wordpress) == 1


def test_reviewer_notes_never_reach_wordpress(monkeypatch):
    """Through the real create_post: check the exact bytes sent."""
    sent = []

    class Answer(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.close()

    def fake_urlopen(request, timeout):
        sent.append(request.data.decode("utf-8"))
        return Answer(json.dumps(WP_ANSWER).encode("utf-8"))

    monkeypatch.setattr(wordpress_publish, "urlopen", fake_urlopen)
    save_draft()
    response = publish()

    assert response.status_code == 200
    assert len(sent) == 1
    assert "SECRET" not in sent[0]
    assert "reviewer" not in sent[0].lower()
    assert "LinkedIn" not in sent[0] and "Första meningen" not in sent[0]
    assert "&lt;tagg&gt; &amp; mer" in json.loads(sent[0])["content"]
    assert PASSWORD not in json.dumps(response.json())


# -------------------- dry run


def test_dry_run_sends_and_saves_nothing(wordpress):
    save_draft()
    response = publish(dry_run=True)

    assert response.status_code == 200
    data = response.json()
    assert data["dry_run"] is True
    assert data["payload"]["status"] == "draft"
    assert "<h2>Avsnitt</h2>" in data["payload"]["content"]
    assert NOTES not in json.dumps(data)
    assert PASSWORD not in json.dumps(data)
    assert wordpress == []
    assert status() == "draft_generated"


def test_dry_run_runs_the_checks(wordpress):
    save_draft(article=ARTICLE + "\nEn siffra [UNVERIFIED].")
    assert publish(dry_run=True).status_code == 409


# -------------------- refused


@pytest.mark.parametrize("key", [None, "wrong-key"])
def test_requires_api_key(wordpress, key):
    save_draft()
    assert publish(key=key).status_code == 401
    assert wordpress == []


def test_unknown_post_gives_404(wordpress):
    response = publish(999)
    assert response.status_code == 404
    assert response.json() == {"detail": "Post not found"}


@pytest.mark.parametrize(
    "body", [{}, {"version": 0}, {"version": "x"}, {"version": 1, "extra": 1}]
)
def test_invalid_body_gives_422(wordpress, body):
    save_draft()
    assert publish(body=body).status_code == 422
    assert wordpress == []


@pytest.mark.parametrize(
    ("post_id", "expected"), [(2, "awaiting_angle"), (4, "approved")]
)
def test_wrong_status_gives_409(wordpress, post_id, expected):
    response = publish(post_id)
    assert response.status_code == 409
    assert f"has status '{expected}'" in response.json()["detail"]
    assert wordpress == []


def test_old_version_gives_409(wordpress):
    save_draft(version=1)
    save_draft(version=2)
    response = publish(body={"version": 1})

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert "Version 1 is not the latest draft of post 1 (latest is 2)" in detail
    assert wordpress == []
    assert status() == "draft_generated"


@pytest.mark.parametrize(
    ("article", "linkedin", "expected"),
    [
        (ARTICLE + "\nPåstående [UNVERIFIED].", LINKEDIN, "[UNVERIFIED]"),
        (ARTICLE, "Text [UNVERIFIED]. Läs mer: [LÄNK]", "[UNVERIFIED]"),
        (ARTICLE + "\nSkrivet av [NAMN].", LINKEDIN, "[NAMN]"),
    ],
)
def test_unverified_or_placeholder_gives_409(wordpress, article, linkedin, expected):
    save_draft(article=article, linkedin=linkedin)
    response = publish()

    assert response.status_code == 409
    assert expected in response.json()["detail"]
    assert wordpress == []
    assert status() == "draft_generated"


def test_publish_in_progress_gives_409(wordpress):
    save_draft()
    publish_store.request_publish("fixture", 1, 1)

    response = publish()

    assert response.status_code == 409
    assert "Check WordPress" in response.json()["detail"]
    assert wordpress == []


def test_missing_wordpress_settings_gives_500(wordpress, monkeypatch):
    monkeypatch.setenv("WORDPRESS_APP_PASSWORD", "")
    save_draft()
    response = publish()

    assert response.status_code == 500
    assert response.json() == {"detail": "WordPress is not configured"}


# -------------------- WordPress or Supabase failed


def failing_wordpress(monkeypatch, error):
    def fake_urlopen(request, timeout):
        raise error

    monkeypatch.setattr(wordpress_publish, "urlopen", fake_urlopen)


def test_wordpress_refused_gives_502_and_allows_a_new_try(monkeypatch):
    body = io.BytesIO(json.dumps({"code": "rest_cannot_create"}).encode("utf-8"))
    failing_wordpress(monkeypatch, HTTPError("u", 403, "Forbidden", {}, body))
    save_draft()

    response = publish()

    assert response.status_code == 502
    assert "did not create the post" in response.json()["detail"]
    assert PASSWORD not in response.text
    assert status() == "draft_generated"


def test_wordpress_timeout_gives_502_and_blocks_a_new_try(monkeypatch):
    failing_wordpress(monkeypatch, URLError(TimeoutError("timed out")))
    save_draft()

    response = publish()

    assert response.status_code == 502
    assert "may exist" in response.json()["detail"]
    assert status() == "publish_requested"
    assert publish().status_code == 409


def test_saving_the_result_fails_gives_502_and_no_second_post(wordpress, monkeypatch):
    def broken(*args):
        raise StoreError("Supabase is down")

    monkeypatch.setattr(publish_api, "mark_published", broken)
    save_draft()

    response = publish()

    assert response.status_code == 502
    assert "created in WordPress" in response.json()["detail"]
    assert "Supabase is down" not in response.text
    assert status() == "publish_requested"
    assert publish().status_code == 409
    assert len(wordpress) == 1


def test_supabase_read_error_gives_502(wordpress, monkeypatch):
    def broken(*args):
        raise StoreError("secret details")

    monkeypatch.setattr(publish_api, "load_publication", broken)
    response = publish()

    assert response.status_code == 502
    assert response.json() == {"detail": "Could not read the post"}
