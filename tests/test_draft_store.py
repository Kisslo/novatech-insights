import io
import json
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlparse

import pytest

import draft_store
from draft_store import (
    DRAFT_STATUS,
    GENERATE_FROM,
    PostNotFound,
    PostNotReady,
    StoreError,
    build_row,
    check_can_generate,
    load_post,
    load_topic,
    save_version,
)

SUPABASE_KEY = "sb_secret_never_in_messages"

POST = {
    "id": 7,
    "topic_id": 42,
    "status": "angle_received",
    "kisslo_angle": "Börja i det lilla.",
}

DRAFT = {
    "article": "# Rubrik\n\nText",
    "linkedin": "Kort text. Läs mer: [LÄNK]",
    "notes": "- Från Claude.",
    "review_notes": "- Strök en floskel.",
    "reviewed": True,
    "warnings": ["Article has 2 words (expected 500–800)."],
    "stats": {"words": 2, "sections": 0, "linkedin_sentences": 2, "unverified": 0},
    "source_news_ids": [11, 12],
    "tokens_in": 1500,
    "tokens_out": 3000,
    "cost": 0.033,
}


@pytest.fixture
def supabase_env(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://test.supabase.co/")
    monkeypatch.setenv("SUPABASE_KEY", SUPABASE_KEY)
    for name in (
        "POSTS_TABLE",
        "DRAFTS_TABLE",
        "TOPICS_OVERVIEW_VIEW",
        "TOPICS_ARTICLES_VIEW",
    ):
        monkeypatch.delenv(name, raising=False)


def fake_supabase(monkeypatch, answers):
    """Replace urlopen for reads and writes. Returns the list of requests.

    `answers` maps (method, table) to the JSON answer, an exception to raise,
    or a function of the request.
    """
    requests = []

    def call(request, timeout):
        requests.append(request)
        table = urlparse(request.full_url).path.rsplit("/", 1)[-1]
        answer = answers[(request.get_method(), table)]
        if callable(answer):
            answer = answer(request)
        if isinstance(answer, Exception):
            raise answer
        return io.BytesIO(json.dumps(answer).encode("utf-8"))

    monkeypatch.setattr("draft_store.urlopen", call)  # writes
    monkeypatch.setattr("label_topics.urlopen", call)  # reads (supabase_get)
    return requests


def query(request):
    return {k: v[0] for k, v in parse_qs(urlparse(request.full_url).query).items()}


def body(request):
    return json.loads(request.data.decode("utf-8"))


# -------------------- fixture: reading


def test_load_post_from_fixture():
    post = load_post("fixture", 1)

    assert post["topic_id"] == 101
    assert post["status"] == "angle_received"
    assert post["kisslo_angle"].startswith("Småföretag ska inte vänta")


def test_load_post_unknown_id_raises_not_found():
    with pytest.raises(PostNotFound, match="Post 999 was not found"):
        load_post("fixture", 999)


def test_unknown_source_is_refused():
    with pytest.raises(StoreError, match="fixture or supabase"):
        load_post("database", 1)


@pytest.mark.parametrize("status", GENERATE_FROM)
def test_check_can_generate_allows_new_and_repeated_drafts(status):
    check_can_generate({**POST, "status": status})


@pytest.mark.parametrize(
    "status", ["awaiting_angle", "awaiting_approval", "approved", "published"]
)
def test_check_can_generate_refuses_other_statuses(status):
    with pytest.raises(PostNotReady, match=f"has status '{status}'"):
        check_can_generate({**POST, "status": status})


def test_fixture_posts_cover_the_endpoint_cases():
    check_can_generate(load_post("fixture", 1))
    check_can_generate(load_post("fixture", 3))  # new version of a draft
    for post_id in (2, 4):
        with pytest.raises(PostNotReady):
            check_can_generate(load_post("fixture", post_id))


def test_load_topic_from_fixture():
    topic = load_topic("fixture", 101)

    assert topic["label"] == "EU ger småföretag vägledning om AI-förordningen"
    assert topic["why_relevant_sv"]
    assert [a["news_id"] for a in topic["articles"]] == [1001, 1002, 1003]


def test_load_topic_unknown_id_raises():
    with pytest.raises(StoreError, match="Topic 999 was not found"):
        load_topic("fixture", 999)


# -------------------- row


def test_build_row_keeps_notes_out_of_the_article():
    row = build_row(POST, DRAFT, "rebut", "claude-sonnet-5-5")

    assert row["post_id"] == 7
    assert row["article_text"] == "# Rubrik\n\nText"
    assert row["linkedin_text"] == "Kort text. Läs mer: [LÄNK]"
    assert row["source_news_ids"] == [11, 12]
    assert row["stance"] == "rebut"
    notes = row["reviewer_notes"]
    assert "- Från Claude." in notes
    assert "- Strök en floskel." in notes
    assert "Warning: Article has 2 words" in notes
    assert "Stance: rebut" in notes
    assert "Cost: $0.0330" in notes
    assert "Från Claude" not in row["article_text"] + row["linkedin_text"]
    assert "version" not in row


# -------------------- fixture: saving


def test_save_version_fixture_writes_numbered_files(monkeypatch, tmp_path):
    monkeypatch.setattr(draft_store, "FIXTURE_OUTPUT_DIR", tmp_path / "drafts")
    row = build_row(POST, DRAFT, "agree", "claude-sonnet-5-5")

    first = save_version("fixture", POST, row)
    second = save_version("fixture", POST, row)
    other = save_version("fixture", {**POST, "id": 8}, {**row, "post_id": 8})

    assert first == {"draft_id": None, "version": 1, "status": DRAFT_STATUS}
    assert second["version"] == 2
    assert other["version"] == 1  # versions are counted per post
    saved = json.loads(
        (tmp_path / "drafts" / "post_7_v2.json").read_text(encoding="utf-8")
    )
    assert saved["article_text"] == "# Rubrik\n\nText"
    assert saved["version"] == 2
    assert saved["status"] == DRAFT_STATUS
    assert saved["created_at"]


# -------------------- supabase: reading


def test_load_post_from_supabase(supabase_env, monkeypatch):
    requests = fake_supabase(monkeypatch, {("GET", "posts"): [POST]})

    assert load_post("supabase", 7) == POST
    assert query(requests[0]) == {
        "select": "id,topic_id,status,kisslo_angle",
        "id": "eq.7",
    }
    assert requests[0].get_header("Apikey") == SUPABASE_KEY


def test_load_post_from_supabase_not_found(supabase_env, monkeypatch):
    fake_supabase(monkeypatch, {("GET", "posts"): []})

    with pytest.raises(PostNotFound):
        load_post("supabase", 7)


def test_load_post_without_supabase_settings(monkeypatch):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_KEY", raising=False)

    with pytest.raises(StoreError, match="SUPABASE_URL and SUPABASE_KEY"):
        load_post("supabase", 7)


def test_read_error_becomes_store_error_without_the_key(supabase_env, monkeypatch):
    error = HTTPError("u", 401, "Unauthorized", {}, None)
    fake_supabase(monkeypatch, {("GET", "posts"): error})

    with pytest.raises(StoreError, match="Check SUPABASE_KEY") as caught:
        load_post("supabase", 7)
    assert SUPABASE_KEY not in str(caught.value)


def test_load_topic_from_supabase_reads_topic_then_articles(supabase_env, monkeypatch):
    overview = [
        {
            "id": 42,
            "score": None,  # not used for a draft
            "article_count": 5,
            "source_count": 3,
            "label": "Rubrik",
            "why_relevant_sv": "Viktigt.",
            "llm_relevance": 4,
        }
    ]
    articles = [
        {
            "topic_id": 42,
            "news_id": 11,
            "title": "Title",
            "source": "Source",
            "link": "https://example.com/1",
            "description": "Description",
            "rank_in_topic": 1,
        }
    ]
    requests = fake_supabase(
        monkeypatch,
        {("GET", "topic_overview"): overview, ("GET", "topic_top_articles"): articles},
    )

    topic = load_topic("supabase", 42)

    assert topic["label"] == "Rubrik"
    assert topic["why_relevant_sv"] == "Viktigt."
    assert [a["news_id"] for a in topic["articles"]] == [11]
    assert query(requests[0])["id"] == "eq.42"
    assert query(requests[1])["topic_id"] == "in.(42)"


def test_load_topic_from_supabase_without_articles(supabase_env, monkeypatch):
    fake_supabase(
        monkeypatch,
        {("GET", "topic_overview"): [{"id": 42}], ("GET", "topic_top_articles"): []},
    )

    with pytest.raises(StoreError, match="Topic 42 cannot be used: .*no articles"):
        load_topic("supabase", 42)


# -------------------- supabase: saving


def test_save_version_supabase_inserts_next_version_then_sets_status(
    supabase_env, monkeypatch
):
    requests = fake_supabase(
        monkeypatch,
        {
            ("GET", "post_drafts"): [{"version": 2}],
            ("POST", "post_drafts"): [{"id": 55, "version": 3}],
            ("PATCH", "posts"): [{"id": 7}],
        },
    )
    row = build_row(POST, DRAFT, "agree", "claude-sonnet-5-5")

    saved = save_version("supabase", POST, row)

    assert saved == {"draft_id": 55, "version": 3, "status": DRAFT_STATUS}
    assert [r.get_method() for r in requests] == ["GET", "POST", "PATCH"]
    assert query(requests[0]) == {
        "select": "version",
        "post_id": "eq.7",
        "order": "version.desc",
        "limit": "1",
    }
    assert body(requests[1]) == {**row, "version": 3}
    assert requests[1].get_header("Prefer") == "return=representation"
    assert query(requests[2]) == {
        "id": "eq.7",
        "status": "in.(angle_received,draft_generated,changes_requested)",
        "select": "id",
    }
    assert body(requests[2]) == {"status": "draft_generated"}


def test_save_version_supabase_first_version_is_one(supabase_env, monkeypatch):
    requests = fake_supabase(
        monkeypatch,
        {
            ("GET", "post_drafts"): [],
            ("POST", "post_drafts"): [{"id": 1, "version": 1}],
            ("PATCH", "posts"): [{"id": 7}],
        },
    )

    saved = save_version("supabase", POST, {"post_id": 7})

    assert saved["version"] == 1
    assert body(requests[1])["version"] == 1


def test_save_version_supabase_uses_table_names_from_env(supabase_env, monkeypatch):
    monkeypatch.setenv("POSTS_TABLE", "posts_test")
    monkeypatch.setenv("DRAFTS_TABLE", "drafts_test")
    requests = fake_supabase(
        monkeypatch,
        {
            ("GET", "drafts_test"): [],
            ("POST", "drafts_test"): [{"id": 1, "version": 1}],
            ("PATCH", "posts_test"): [{"id": 7}],
        },
    )

    save_version("supabase", POST, {"post_id": 7})

    assert len(requests) == 3


def test_invalid_table_name_is_refused(supabase_env, monkeypatch):
    monkeypatch.setenv("DRAFTS_TABLE", "post_drafts?select=*")

    with pytest.raises(StoreError, match="not a valid view name"):
        save_version("supabase", POST, {"post_id": 7})


@pytest.mark.parametrize(
    ("answer", "message"),
    [
        (HTTPError("u", 403, "Forbidden", {}, None), "Check SUPABASE_KEY"),
        (HTTPError("u", 404, "Not Found", {}, None), "'post_drafts' was not found"),
        (HTTPError("u", 409, "Conflict", {}, None), "saved at the same time"),
        (HTTPError("u", 400, "Bad Request", {}, None), "HTTP 400"),
        (URLError("no network"), "Could not reach Supabase"),
        ([], "was not saved"),
        ({"message": "odd"}, "Unexpected answer"),
    ],
)
def test_save_version_supabase_failed_insert_leaves_status(
    supabase_env, monkeypatch, answer, message
):
    requests = fake_supabase(
        monkeypatch,
        {("GET", "post_drafts"): [], ("POST", "post_drafts"): answer},
    )

    with pytest.raises(StoreError, match=message) as caught:
        save_version("supabase", POST, {"post_id": 7})

    assert [r.get_method() for r in requests] == ["GET", "POST"]  # no PATCH
    assert SUPABASE_KEY not in str(caught.value)


def test_save_version_supabase_reports_saved_draft_when_status_changed(
    supabase_env, monkeypatch
):
    fake_supabase(
        monkeypatch,
        {
            ("GET", "post_drafts"): [],
            ("POST", "post_drafts"): [{"id": 1, "version": 1}],
            ("PATCH", "posts"): [],  # the status no longer allows it
        },
    )

    with pytest.raises(StoreError, match="version 1 for post 7 was saved, but"):
        save_version("supabase", POST, {"post_id": 7})
