import json
from urllib.error import HTTPError

import pytest
from fastapi.testclient import TestClient

import draft_api
import draft_store
from content_tools import ClaudeError
from draft_api import draft_buttons, format_preview, headline_and_intro
from draft_article import REVIEW_SYSTEM_PROMPT, STANCES, STYLE_GUIDE
from draft_store import StoreError
from telegram_api import app

API_KEY = "test-key-that-is-long-enough-1234567890"
SUPABASE_KEY = "sb_secret_never_in_answers"

client = TestClient(app)

ARTICLE = "\n".join(
    [
        "# AI-regler: börja nu",
        "",
        "Ingressen säger det viktigaste <först>.",
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
        "- Exempel Affärer: Nya regler – "
        "https://example.com/affarer/ai-forordningen-smaforetag",
        "- Example Policy Weekly: Chatbots – "
        "https://example.com/policy/ai-act-chatbot-transparency",
    ]
)
LINKEDIN = "Första meningen. Andra meningen. Tredje meningen. Läs mer: [LÄNK]"


def answer(notes_tag, notes):
    return (
        f"<article_draft>\n{ARTICLE}\n</article_draft>\n"
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
    draft_api._in_progress.clear()


@pytest.fixture
def claude(monkeypatch):
    """Replace call_claude in the endpoint. Returns the list of calls made."""
    calls = []

    def call(model, system_prompt, prompt, effort, max_tokens):
        calls.append((system_prompt, prompt))
        if system_prompt == REVIEW_SYSTEM_PROMPT:
            return answer("review_notes", "- Strök en floskel."), 500, 1000
        return answer("reviewer_notes", "- Bara för granskaren."), 1000, 2000

    monkeypatch.setattr(draft_api, "call_claude", call)
    return calls


def post_draft(post_id, key=API_KEY, **kwargs):
    headers = {"X-API-Key": key} if key is not None else {}
    return client.post(f"/drafts/{post_id}", headers=headers, **kwargs)


def saved_files(tmp_path):
    folder = tmp_path / "drafts"
    return sorted(p.name for p in folder.iterdir()) if folder.exists() else []


# -------------------- access and status


@pytest.mark.parametrize("key", [None, "wrong-key"])
def test_draft_requires_api_key(claude, key):
    response = post_draft(1, key=key)

    assert response.status_code == 401
    assert claude == []


def test_unknown_post_gives_404(claude):
    response = post_draft(999)

    assert response.status_code == 404
    assert response.json() == {"detail": "Post not found"}
    assert claude == []


@pytest.mark.parametrize(
    ("post_id", "status"), [(2, "awaiting_angle"), (4, "approved")]
)
def test_post_in_wrong_status_gives_409(claude, tmp_path, post_id, status):
    response = post_draft(post_id)

    assert response.status_code == 409
    assert f"has status '{status}'" in response.json()["detail"]
    assert claude == []
    assert saved_files(tmp_path) == []


def test_topic_without_label_gives_409(claude):
    response = post_draft(5)

    assert response.status_code == 409
    assert response.json() == {"detail": "Topic 106 has no label."}
    assert claude == []


@pytest.mark.parametrize("body", [{"stance": "maybe"}, {"stanse": "agree"}])
def test_invalid_body_gives_422(claude, body):
    response = post_draft(1, json=body)

    assert response.status_code == 422
    assert claude == []


def test_post_id_must_be_positive(claude):
    assert post_draft(0).status_code == 422
    assert post_draft("abc").status_code == 422


def test_body_accepts_the_same_stances_as_the_generator():
    allowed = draft_api.DraftRequest.model_json_schema()["properties"]["stance"]

    assert tuple(allowed["enum"]) == STANCES


# -------------------- a successful call


def test_draft_is_written_reviewed_saved_and_returned(claude, tmp_path):
    response = post_draft(1)

    assert response.status_code == 200
    data = response.json()
    assert data["dry_run"] is False
    assert data["source"] == "fixture"
    assert (data["post_id"], data["topic_id"]) == (1, 101)
    assert (data["draft_id"], data["version"]) == (None, 1)
    assert data["status"] == "draft_generated"
    assert data["stance"] == "agree"
    assert data["reviewed"] is True
    assert data["warnings"] == []
    assert data["stats"]["words"] == 611
    assert data["cost_usd"] == 0.033
    assert data["article"] == ARTICLE
    assert data["linkedin"] == LINKEDIN
    assert data["source_news_ids"] == [1001, 1002, 1003]
    # Two calls, both with the style guide; Kisslo's angle is in the first.
    assert len(claude) == 2
    assert all(STYLE_GUIDE in prompt for _, prompt in claude)
    assert "Småföretag ska inte vänta på att reglerna blir klara" in claude[0][1]
    assert "Stance: agree." in claude[0][1]
    # Reviewer notes are returned and stored on their own, never in the texts.
    assert "Bara för granskaren" in data["reviewer_notes"]
    assert "Strök en floskel" in data["reviewer_notes"]
    assert "Bara för granskaren" not in data["article"] + data["linkedin"]
    assert "Bara för granskaren" not in data["preview"]["text"]
    # One saved version with the same content.
    assert saved_files(tmp_path) == ["post_1_v1.json"]
    saved = json.loads(
        (tmp_path / "drafts" / "post_1_v1.json").read_text(encoding="utf-8")
    )
    assert saved["article_text"] == ARTICLE
    assert saved["linkedin_text"] == LINKEDIN
    assert saved["reviewer_notes"] == data["reviewer_notes"]
    assert saved["source_news_ids"] == [1001, 1002, 1003]
    assert saved["stance"] == "agree"


def test_preview_is_a_short_telegram_message(claude):
    preview = post_draft(1).json()["preview"]

    assert preview["parse_mode"] == "HTML"
    assert preview["text"] == (
        "<b>Utkast v1: AI-regler: börja nu</b>\n"
        "\n"
        "Ingressen säger det viktigaste &lt;först&gt;.\n"
        "\n"
        "<b>LinkedIn</b>\n"
        "Första meningen. Andra meningen. Tredje meningen. Läs mer: [LÄNK]\n"
        "\n"
        "Ord: 611 · Avsnitt: 3 · [UNVERIFIED]: 0 · Varningar: 0"
    )
    assert preview["buttons"] == [
        {"text": "Publicera", "callback_data": "publish:1:1"},
        {"text": "Ändra", "callback_data": "revise:1:1"},
        {"text": "Skippa", "callback_data": "keep:1:1"},
    ]


def test_buttons_follow_the_new_version(claude):
    post_draft(3)
    second = post_draft(3).json()

    assert [b["callback_data"] for b in second["preview"]["buttons"]] == [
        "publish:3:2",
        "revise:3:2",
        "keep:3:2",
    ]


def test_a_new_call_creates_a_new_version(claude, tmp_path):
    first = post_draft(3)  # post 3 already has status draft_generated
    second = post_draft(3)

    assert (first.status_code, second.status_code) == (200, 200)
    assert (first.json()["version"], second.json()["version"]) == (1, 2)
    assert saved_files(tmp_path) == ["post_3_v1.json", "post_3_v2.json"]


def test_stance_rebut_reaches_the_prompt_and_the_saved_row(claude, tmp_path):
    response = post_draft(1, json={"stance": "rebut"})

    assert response.json()["stance"] == "rebut"
    assert "Stance: rebut." in claude[0][1]
    saved = json.loads(
        (tmp_path / "drafts" / "post_1_v1.json").read_text(encoding="utf-8")
    )
    assert saved["stance"] == "rebut"


# -------------------- dry run


def test_dry_run_makes_no_call_and_saves_nothing(claude, tmp_path):
    response = post_draft(1, params={"dry_run": "true"})

    assert response.status_code == 200
    data = response.json()
    assert data["dry_run"] is True
    assert (data["post_id"], data["topic_id"]) == (1, 101)
    assert data["model"] == "claude-sonnet-5-5"
    assert STYLE_GUIDE in data["prompt"]
    assert data["estimate"]["max_output_tokens"] == 11000
    assert 0.10 < data["estimate"]["max_cost_usd"] < 0.13
    assert claude == []
    assert saved_files(tmp_path) == []


def test_dry_run_still_checks_the_post(claude):
    assert post_draft(999, params={"dry_run": "true"}).status_code == 404
    assert post_draft(2, params={"dry_run": "true"}).status_code == 409


# -------------------- failures


def test_claude_failure_gives_502_and_saves_nothing(monkeypatch, tmp_path):
    def failing_call(*args):
        raise ClaudeError("The API key was rejected. Check ANTHROPIC_API_KEY in .env.")

    monkeypatch.setattr(draft_api, "call_claude", failing_call)

    response = post_draft(1)

    assert response.status_code == 502
    assert response.json() == {"detail": "Could not write the draft"}
    assert saved_files(tmp_path) == []
    assert draft_api._in_progress == set()


def test_unreadable_answer_gives_502_and_saves_nothing(monkeypatch, tmp_path):
    monkeypatch.setattr(draft_api, "call_claude", lambda *args: ("Inga taggar", 1, 1))

    response = post_draft(1)

    assert response.status_code == 502
    assert saved_files(tmp_path) == []


def test_failed_review_still_saves_the_draft_with_a_warning(monkeypatch, tmp_path):
    def call(model, system_prompt, prompt, effort, max_tokens):
        if system_prompt == REVIEW_SYSTEM_PROMPT:
            raise ClaudeError("Rate limit reached. Wait a minute and try again.")
        return answer("reviewer_notes", "- En anteckning."), 1000, 2000

    monkeypatch.setattr(draft_api, "call_claude", call)

    data = post_draft(1).json()

    assert data["reviewed"] is False
    assert "Review step failed" in data["warnings"][0]
    assert "texten är inte granskad" in data["preview"]["text"]
    assert saved_files(tmp_path) == ["post_1_v1.json"]


def test_save_failure_gives_502_without_details(claude, monkeypatch):
    def failing_save(source, post, row):
        raise StoreError(f"Supabase refused to write ({SUPABASE_KEY})")

    monkeypatch.setattr(draft_api, "save_version", failing_save)

    response = post_draft(1)

    assert response.status_code == 502
    assert response.json() == {"detail": "Could not save the draft"}
    assert SUPABASE_KEY not in response.text
    assert draft_api._in_progress == set()


def test_missing_drafts_table_gives_502_before_claude_is_called(claude, monkeypatch):
    def failing_check(source):
        raise StoreError(f"View 'post_drafts' was not found ({SUPABASE_KEY})")

    monkeypatch.setattr(draft_api, "check_can_save", failing_check)

    response = post_draft(1)

    assert response.status_code == 502
    assert response.json() == {"detail": "Drafts cannot be saved"}
    assert SUPABASE_KEY not in response.text
    assert claude == []  # nothing was paid for
    assert draft_api._in_progress == set()


def test_supabase_read_failure_gives_502_without_details(claude, monkeypatch):
    monkeypatch.setenv("TELEGRAM_SOURCE", "supabase")
    monkeypatch.setenv("SUPABASE_URL", "https://test.supabase.co")
    monkeypatch.setenv("SUPABASE_KEY", SUPABASE_KEY)

    def failing_urlopen(request, timeout):
        raise HTTPError(request.full_url, 500, "Server Error", {}, None)

    monkeypatch.setattr("label_topics.urlopen", failing_urlopen)

    response = post_draft(1)

    assert response.status_code == 502
    assert response.json() == {"detail": "Could not read the post"}
    assert SUPABASE_KEY not in response.text
    assert claude == []


def test_invalid_source_gives_500(claude, monkeypatch):
    monkeypatch.setenv("TELEGRAM_SOURCE", "database")

    response = post_draft(1)

    assert response.status_code == 500
    assert claude == []


def test_second_request_for_the_same_post_is_refused(claude, tmp_path):
    draft_api._in_progress.add(1)  # a draft for post 1 is being written

    response = post_draft(1)

    assert response.status_code == 409
    assert "already being written for post 1" in response.json()["detail"]
    assert claude == []
    assert saved_files(tmp_path) == []
    assert post_draft(3).status_code == 200  # other posts are not blocked


# -------------------- preview helpers


def test_headline_and_intro():
    assert headline_and_intro("# Rubrik\n\nIngress.\n\n## Avsnitt\n\nText") == (
        "Rubrik",
        "Ingress.",
    )
    assert headline_and_intro("Bara text") == ("", "Bara text")
    assert headline_and_intro("") == ("", "")


def test_format_preview_shortens_long_texts_and_stays_within_telegram_limit():
    draft = {
        "article": "# " + "R" * 500 + "\n\n" + "i" * 5000,
        "linkedin": "l" * 5000,
        "stats": {"words": 1, "sections": 0, "linkedin_sentences": 1, "unverified": 2},
        "warnings": ["a", "b"],
        "reviewed": True,
    }

    text = format_preview(draft, 1, 3)["text"]

    assert len(text) < 4096
    assert text.startswith("<b>Utkast v3: RRR")
    assert "[UNVERIFIED]: 2 · Varningar: 2" in text


def test_draft_buttons_do_not_reuse_the_topic_prefixes():
    data = [b["callback_data"] for b in draft_buttons(7, 2)]

    assert data == ["publish:7:2", "revise:7:2", "keep:7:2"]
    assert not any(d.startswith(("write:", "skip:")) for d in data)


def test_draft_buttons_stay_within_telegram_limit():
    for button in draft_buttons(10**18, 10**6):
        assert len(button["callback_data"].encode("utf-8")) <= 64
