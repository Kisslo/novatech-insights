"""Small API for n8n: the top N topics as ready Telegram messages (issue #42).

One endpoint:
    GET /telegram/top?n=5   with header X-API-Key: <TELEGRAM_API_KEY>

The API only reads. It never calls Claude and never writes to Supabase:
labels are made in advance with `label_topics.py --source supabase --save`.
The text and buttons come from telegram_format.format_topic(); this file is
only a thin HTTP wrapper around it.

Settings in .env:
    TELEGRAM_API_KEY  long random key that n8n sends in X-API-Key (required)
    TELEGRAM_SOURCE   fixture (default, tests/fixtures/sample_topics.json)
                      or supabase (same views as label_topics.py)

Run locally (only reachable from this computer; the tunnel forwards to it):
    uv run uvicorn telegram_api:app --app-dir src --port 8000
"""

import logging
import os
import secrets

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Header, HTTPException, Query

from label_topics import (
    DEFAULT_FIXTURE,
    ReadError,
    existing_labels,
    load_fixture,
    load_supabase,
    select_top,
)
from telegram_format import format_topic

load_dotenv()

MAX_TOPICS = 20
DEFAULT_TOPICS = 5
FORMAT_EXTRA = 5  # extra topics read in case a topic cannot be formatted
MIN_KEY_LENGTH = 32
SOURCES = ("fixture", "supabase")

logger = logging.getLogger("telegram_api")

# The automatic docs pages are turned off: the API is reachable from the
# internet through the tunnel, and n8n does not need them.
app = FastAPI(
    title="Novatech Telegram API", docs_url=None, redoc_url=None, openapi_url=None
)


def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    """Stop the request unless the X-API-Key header has the right key.

    FastAPI reads the header X-API-Key into x_api_key. The key is compared
    with secrets.compare_digest, which takes the same time whether the first
    or the last character is wrong, so the key cannot be guessed by timing.
    Without a long enough key in .env, every request is refused (fail closed).
    """
    expected = os.getenv("TELEGRAM_API_KEY", "").strip()
    if len(expected) < MIN_KEY_LENGTH:
        logger.error("TELEGRAM_API_KEY is missing or shorter than %d", MIN_KEY_LENGTH)
        raise HTTPException(status_code=503, detail="API key is not configured")
    if x_api_key is None or not secrets.compare_digest(
        x_api_key.encode("utf-8"), expected.encode("utf-8")
    ):
        raise HTTPException(status_code=401, detail="Invalid or missing API key")


def read_labelled_topics(source: str, count: int) -> tuple[list[dict], list[dict]]:
    """Labelled topics, highest score first, plus topics skipped as invalid."""
    if source == "supabase":
        return load_supabase(count, labelled_only=True)
    topics, skipped = load_fixture(DEFAULT_FIXTURE)
    labelled = [topic for topic in topics if existing_labels(topic) is not None]
    return select_top(labelled, count), skipped


@app.get("/telegram/top", dependencies=[Depends(require_api_key)])
def telegram_top(n: int = Query(DEFAULT_TOPICS, ge=1, le=MAX_TOPICS)) -> dict:
    """The top n labelled topics as Telegram messages with Skriv/Skippa buttons.

    A topic that cannot be formatted is reported in "skipped"; a few extra
    topics are read so that it does not make the answer shorter than n.
    """
    source = os.getenv("TELEGRAM_SOURCE", "fixture").strip()
    if source not in SOURCES:
        logger.error("TELEGRAM_SOURCE must be fixture or supabase, not %r", source)
        raise HTTPException(status_code=500, detail="Server is not configured")
    try:
        topics, skipped = read_labelled_topics(source, n + FORMAT_EXTRA)
    except ReadError as error:
        # The details stay in the server log; n8n only gets a short message.
        logger.error("Could not read topics: %s", error)
        raise HTTPException(status_code=502, detail="Could not read topics") from None

    messages = []
    for topic in topics:
        if len(messages) == n:
            break
        try:
            messages.append(format_topic(topic, rank=len(messages) + 1))
        except ValueError as error:
            skipped.append({"topic_id": topic["id"], "reason": str(error)})
    return {
        "source": source,
        "requested": n,
        "count": len(messages),
        "topics": messages,
        "skipped": skipped,
    }
