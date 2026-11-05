"""Check or backfill normalized source names in existing news articles."""

import argparse
import json
import os
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from dotenv import load_dotenv

if __package__:
    from .source_normalization import normalize_source
else:
    from source_normalization import normalize_source

ROOT = Path(__file__).resolve().parent.parent
PAGE_SIZE = 500


def request_json(url, key, method="GET", payload=None):
    """Call the REST API without exposing credentials in error messages."""
    headers = {"apikey": key}
    data = None

    if payload is not None:
        headers["Content-Type"] = "application/json"
        headers["Prefer"] = "return=representation"
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    request = Request(
        url,
        data=data,
        headers=headers,
        method=method,
    )

    try:
        with urlopen(request, timeout=30) as response:
            result = json.load(response)
    except HTTPError as error:
        raise RuntimeError(
            f"REST request failed: HTTP {error.code}. "
            "Check the migration and backend permissions."
        ) from None
    except URLError, TimeoutError, OSError:
        raise RuntimeError("REST connection failed or was interrupted.") from None
    except ValueError, UnicodeError:
        raise RuntimeError("REST API returned invalid JSON.") from None

    if not isinstance(result, list):
        raise RuntimeError("Expected a list of rows from the REST API.")

    return result


def equality_filter(value):
    """Build a PostgREST equality filter, including NULL."""
    if value is None:
        return "is.null"

    return f"eq.{value}"


def validate_article(article, previous_id):
    """Reject unexpected data before using it in an update."""
    required = {"id", "source", "source_normalized"}

    if not isinstance(article, dict) or not required.issubset(article):
        raise RuntimeError("An article is missing required fields.")

    news_id = article["id"]
    if type(news_id) is not int or news_id <= previous_id:
        raise RuntimeError("Article IDs must be positive and strictly increasing.")

    for field in ("source", "source_normalized"):
        value = article[field]
        if value is not None and not isinstance(value, str):
            raise RuntimeError(f"Unexpected value type for {field}.")


def update_article(url, key, article, normalized):
    """Update one key only if the source and old key are unchanged."""
    query = urlencode(
        {
            "id": f"eq.{article['id']}",
            "source": equality_filter(article["source"]),
            "source_normalized": equality_filter(article["source_normalized"]),
            "select": "id,source,source_normalized",
        }
    )

    saved = request_json(
        f"{url}/rest/v1/news?{query}",
        key,
        method="PATCH",
        payload={"source_normalized": normalized},
    )

    if not saved:
        raise RuntimeError(
            "An update matched no visible row. The article may have changed "
            "during the run, or update access may be missing. "
            "Check permissions and rerun the check."
        )

    if (
        len(saved) != 1
        or not isinstance(saved[0], dict)
        or saved[0].get("id") != article["id"]
        or saved[0].get("source") != article["source"]
        or saved[0].get("source_normalized") != normalized
    ):
        raise RuntimeError("The API did not confirm the expected update.")


def backfill_sources(url, key, apply=False):
    """Scan all news rows; write only when explicitly enabled."""
    if not url or not key:
        raise ValueError("Missing SUPABASE_URL or SUPABASE_KEY.")

    url = url.rstrip("/")
    last_id = 0
    scanned = 0
    needs_update = 0
    updated = 0

    while True:
        query = urlencode(
            {
                "select": "id,source,source_normalized",
                "id": f"gt.{last_id}",
                "order": "id.asc",
                "limit": PAGE_SIZE,
            }
        )

        articles = request_json(f"{url}/rest/v1/news?{query}", key)

        if not articles:
            break

        for article in articles:
            validate_article(article, last_id)

            normalized = normalize_source(article["source"])
            scanned += 1

            if article["source_normalized"] != normalized:
                needs_update += 1

                if apply:
                    update_article(url, key, article, normalized)
                    updated += 1

            last_id = article["id"]

        print(
            f"Scanned: {scanned}; "
            f"needing normalization: {needs_update}; "
            f"updated: {updated}"
        )

    return {
        "scanned": scanned,
        "needs_update": needs_update,
        "updated": updated,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Check or backfill existing news source comparison keys."
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Update source_normalized. Default: read-only check.",
    )
    args = parser.parse_args()

    load_dotenv(ROOT / ".env")
    url = os.getenv("SUPABASE_URL", "").strip().rstrip("/")
    key = os.getenv("SUPABASE_KEY", "").strip()

    if args.apply:
        print("Apply mode: only source_normalized will be updated.")
    else:
        print("Read-only check. No database values will be changed.")

    try:
        result = backfill_sources(url, key, apply=args.apply)
    except (ValueError, RuntimeError) as error:
        message = f"Stopped: {error}"
        if args.apply:
            message += (
                " Earlier updates may already be saved. "
                "Rerunning skips keys that are already correct."
            )
        raise SystemExit(message) from None

    print(
        f"Finished. Scanned: {result['scanned']}; "
        f"needing normalization: {result['needs_update']}; "
        f"updated: {result['updated']}."
    )


if __name__ == "__main__":
    main()
