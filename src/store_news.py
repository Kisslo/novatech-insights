import argparse
import csv
import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
CSV_FILE = ROOT / "data" / "news.csv"

FIELDS = ["title", "link", "source", "published", "subject", "description"]
BATCH_SIZE = 100


def load_articles():
    """Read and validate unique articles from the last seven days."""
    now = datetime.now(UTC)
    cutoff = now - timedelta(days=7)
    articles = {}
    skipped = 0
    duplicates = 0

    with CSV_FILE.open(encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)

        if reader.fieldnames != FIELDS:
            raise ValueError(f"Unexpected CSV columns: {reader.fieldnames}")

        for row in reader:
            article = {field: (row.get(field) or "").strip() for field in FIELDS}

            try:
                published = datetime.fromisoformat(article["published"])
            except ValueError:
                skipped += 1
                continue

            if (
                not article["title"]
                or not article["link"]
                or not article["source"]
                or published.tzinfo is None
                or not cutoff <= published <= now
            ):
                skipped += 1
                continue

            if article["link"] in articles:
                duplicates += 1
                continue

            article["published"] = (
                published.astimezone(UTC)
                .isoformat(timespec="seconds")
                .replace("+00:00", "Z")
            )
            articles[article["link"]] = article

    print(f"Valid unique articles: {len(articles)}")
    print(f"Rows skipped as invalid or outside last 7 days: {skipped}")
    print(f"Duplicate CSV links skipped: {duplicates}")

    return list(articles.values())


def upload_articles(articles):
    """Insert articles into Supabase without changing existing links."""
    load_dotenv(ROOT / ".env")

    url = os.getenv("SUPABASE_URL", "").strip().rstrip("/")
    key = os.getenv("SUPABASE_KEY", "").strip()

    if not url or not key:
        raise ValueError("Missing SUPABASE_URL or SUPABASE_KEY in .env")

    if not articles:
        print("No valid articles to upload.")
        return

    inserted = 0
    duplicates = 0

    for start in range(0, len(articles), BATCH_SIZE):
        batch = articles[start : start + BATCH_SIZE]

        request = Request(
            f"{url}/rest/v1/news?on_conflict=link&select=id",
            data=json.dumps(batch, ensure_ascii=False).encode("utf-8"),
            headers={
                "apikey": key,
                "Content-Type": "application/json",
                "Prefer": (
                    "resolution=ignore-duplicates,return=representation,missing=default"
                ),
            },
            method="POST",
        )

        try:
            with urlopen(request, timeout=30) as response:
                saved = json.load(response)
        except HTTPError as error:
            raise RuntimeError(
                f"Upload stopped: HTTP {error.code}. "
                "Earlier batches may already be saved. "
                "Rerunning skips existing links."
            ) from None
        except (URLError, TimeoutError) as error:
            raise RuntimeError(
                "Connection interrupted. Some articles may already be saved. "
                "Rerunning skips existing links."
            ) from error

        inserted += len(saved)
        duplicates += len(batch) - len(saved)

        print(f"Processed {start + len(batch)}/{len(articles)} articles")

    print(f"New articles inserted: {inserted}")
    print(f"Existing links skipped: {duplicates}")


def main():
    parser = argparse.ArgumentParser(
        description="Validate RSS articles and optionally upload to Supabase."
    )
    parser.add_argument(
        "--upload",
        action="store_true",
        help="Upload validated articles to the Supabase news table",
    )
    args = parser.parse_args()

    articles = load_articles()

    if args.upload:
        upload_articles(articles)
    else:
        print("Validation only. Nothing uploaded or changed.")
        print("Use --upload to save articles to Supabase.")


if __name__ == "__main__":
    main()
