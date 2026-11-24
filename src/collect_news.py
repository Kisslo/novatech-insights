import argparse
import csv
import json
import os
import sys
import urllib.request
import xml.etree.ElementTree as ET
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from http.client import HTTPException
from pathlib import Path
from time import perf_counter
from urllib.error import URLError

from dotenv import load_dotenv

if __package__:
    from .pipeline_monitoring import (
        PipelineMonitoringError,
        build_supabase_request,
        create_pipeline_run,
        finish_pipeline_run,
    )
else:
    from pipeline_monitoring import (
        PipelineMonitoringError,
        build_supabase_request,
        create_pipeline_run,
        finish_pipeline_run,
    )

ROOT = Path(__file__).resolve().parent.parent
FOLDER = ROOT / "data"
SOURCES_FILE = FOLDER / "sources.csv"
OUTPUT_FILE = FOLDER / "news.csv"

# Shared monitoring contract (see pipeline_monitoring.py and #79).
STAGE = "collection"
MODE = "write"  # The collector saves its result to news.csv.
REQUIRED_SOURCE_COLUMNS = ("name", "feed_url")

FIELDS = ["title", "link", "source", "published", "subject", "description"]

# Change this number if the team wants a different time window.
MAX_AGE_DAYS = 7


def parse_date(value):
    """Read an RSS or ISO date and convert it to UTC."""
    value = (value or "").strip()

    if not value:
        return None

    try:
        date = parsedate_to_datetime(value)
    except ValueError, TypeError, OverflowError:
        try:
            date = datetime.fromisoformat(value)
        except ValueError, TypeError, OverflowError:
            return None

    # Do not guess the timezone when it is missing.
    if date.tzinfo is None:
        return None

    return date.astimezone(UTC)


def format_date(date):
    """Save a consistent ISO 8601 timestamp in UTC."""
    return date.isoformat(timespec="seconds").replace("+00:00", "Z")


class DescriptionParser(HTMLParser):
    """Extract plain text and preserve common HTML text boundaries."""

    SEPARATOR_TAGS = {
        "address",
        "article",
        "blockquote",
        "br",
        "div",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "hr",
        "li",
        "ol",
        "p",
        "pre",
        "section",
        "table",
        "td",
        "th",
        "tr",
        "ul",
    }

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag in self.SEPARATOR_TAGS:
            self.parts.append(" ")

    def handle_endtag(self, tag):
        if tag in self.SEPARATOR_TAGS:
            self.parts.append(" ")

    def handle_data(self, data):
        self.parts.append(data)


def clean_description(value):
    """Remove HTML formatting and normalize whitespace."""
    parser = DescriptionParser()
    parser.feed(value or "")
    parser.close()
    return " ".join("".join(parser.parts).split())


class CollectionConfigError(RuntimeError):
    """Raised when the source list cannot be used."""


class CollectionSaveError(RuntimeError):
    """Raised when news.csv cannot be written."""


def request_json(url, key, *, method="GET", payload=None):
    """Send one request to Supabase REST and return the JSON answer."""
    request = build_supabase_request(url, key, method=method, payload=payload)
    with urllib.request.urlopen(request, timeout=60) as response:
        body = response.read().decode("utf-8")
    return json.loads(body) if body.strip() else []


def empty_metrics():
    """All counters saved in pipeline_runs.metrics."""
    return {
        "feeds_configured": 0,
        "feeds_attempted": 0,
        "feeds_succeeded": 0,
        "feeds_failed": 0,
        "feeds_unsupported": 0,
        "feeds_skipped_missing_url": 0,
        "items_fetched": 0,
        "articles_new": 0,
        "articles_duplicate": 0,
        "articles_rejected": 0,
        "articles_rejected_missing_fields": 0,
        "articles_rejected_date": 0,
        "existing_rows_removed": 0,
        "descriptions_added": 0,
        "articles_saved": 0,
        "duration_seconds": None,
    }


def empty_details():
    """Feed-level errors and run-level errors saved in pipeline_runs.details."""
    return {
        "failed_feeds": {},
        "unsupported_feeds": [],
        "skipped_feeds": [],
        "run_error": None,
        "monitoring_error": None,
    }


def load_sources(path):
    """Read and check the source list. Raises CollectionConfigError."""
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as file:
            reader = csv.DictReader(file)
            columns = reader.fieldnames or []
            missing = [name for name in REQUIRED_SOURCE_COLUMNS if name not in columns]
            if missing:
                raise CollectionConfigError(
                    f"Source list {path.name} is missing columns: {', '.join(missing)}"
                )
            sources = list(reader)
    except FileNotFoundError as error:
        raise CollectionConfigError(f"Source list not found: {path}") from error
    except (OSError, csv.Error, UnicodeDecodeError) as error:
        raise CollectionConfigError(
            f"Source list {path.name} cannot be read: {error}"
        ) from error

    if not any((source.get("feed_url") or "").strip() for source in sources):
        raise CollectionConfigError(f"Source list {path.name} has no feed URLs.")
    return sources


def load_existing_articles(path, cutoff, now, metrics):
    """Keep previously saved articles that still pass the date filter."""
    articles = {}
    if not path.exists():
        return articles

    with path.open("r", encoding="utf-8-sig", newline="") as file:
        for row in csv.DictReader(file):
            date = parse_date(row.get("published"))
            title = (row.get("title") or "").strip()
            link = (row.get("link") or "").strip()

            if not title or not link or date is None or not cutoff <= date <= now:
                metrics["existing_rows_removed"] += 1
                continue

            articles[link] = {
                "title": title,
                "link": link,
                "source": row.get("source") or "",
                "published": format_date(date),
                "subject": row.get("subject") or "",
                "description": row.get("description") or "",
            }
    return articles


def read_feed(feed_url):
    """Download and parse one RSS feed. Returns the XML root."""
    request = urllib.request.Request(
        feed_url,
        headers={"User-Agent": "NovatechStudentRSS/1.0"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return ET.fromstring(response.read())


def collect_feed(name, channel, articles, cutoff, now, metrics):
    """Add the new articles from one feed and update the counters."""
    items = channel.findall("item")
    metrics["items_fetched"] += len(items)

    new_count = 0
    skipped_dates = 0
    descriptions_added = 0

    for item in items:
        title = item.findtext("title", default="").strip()
        link = item.findtext("link", default="").strip()
        published = item.findtext("pubDate", default="").strip()
        description = clean_description(item.findtext("description", default=""))

        if not title or not link:
            metrics["articles_rejected_missing_fields"] += 1
            continue

        # Fill missing descriptions without adding duplicate articles.
        # Preserve the existing title, date, source and subject.
        if link in articles:
            metrics["articles_duplicate"] += 1
            if description and not articles[link].get("description"):
                articles[link]["description"] = description
                descriptions_added += 1
            continue

        date = parse_date(published)

        if date is None or not cutoff <= date <= now:
            metrics["articles_rejected_date"] += 1
            skipped_dates += 1
            continue

        articles[link] = {
            "title": title,
            "link": link,
            "source": name,
            "published": format_date(date),
            "subject": "",
            "description": description,
        }
        new_count += 1

    metrics["articles_new"] += new_count
    metrics["descriptions_added"] += descriptions_added

    if new_count:
        print(f"Feed read successfully: {name}")
    else:
        print(f"Feed read successfully: {name} (no new articles added)")
    print(f"Fetched RSS items: {len(items)}")
    print(f"New articles: {new_count}")
    print(f"Existing articles given descriptions: {descriptions_added}")
    print(f"Skipped because of date: {skipped_dates}")


def save_articles(path, articles):
    """Sort newest first and save through a temporary file."""
    sorted_articles = sorted(
        articles.values(),
        key=lambda article: article["published"],
        reverse=True,
    )
    temporary_file = path.with_suffix(".tmp")
    try:
        with temporary_file.open("w", encoding="utf-8-sig", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=FIELDS)
            writer.writeheader()
            writer.writerows(sorted_articles)
        temporary_file.replace(path)
    except OSError as error:
        temporary_file.unlink(missing_ok=True)
        raise CollectionSaveError(f"Could not save {path}: {error}") from error


def collect(sources_file, output_file, now, metrics, details):
    """Read every feed and save news.csv. Updates metrics and details."""
    cutoff = now - timedelta(days=MAX_AGE_DAYS)
    sources = load_sources(sources_file)
    metrics["feeds_configured"] = len(sources)

    # Check previously saved articles using the same date filter.
    articles = load_existing_articles(output_file, cutoff, now, metrics)

    for source in sources:
        name = (source.get("name") or "").strip()
        feed_url = (source.get("feed_url") or "").strip()
        name = name or feed_url

        if not feed_url:
            metrics["feeds_skipped_missing_url"] += 1
            details["skipped_feeds"].append(name)
            print(f"Skipped feed {name}: missing URL.")
            continue

        metrics["feeds_attempted"] += 1
        print(f"\nReading: {name}")

        try:
            root = read_feed(feed_url)
        except (ValueError, URLError, OSError, HTTPException, ET.ParseError) as error:
            metrics["feeds_failed"] += 1
            details["failed_feeds"][name] = f"{type(error).__name__}: {error}"
            print(f"Feed failed: {name} ({type(error).__name__}: {error})")
            continue

        channel = root.find("channel")

        if channel is None:
            metrics["feeds_unsupported"] += 1
            details["unsupported_feeds"].append(name)
            print(f"Unsupported feed format: {name}")
            continue

        metrics["feeds_succeeded"] += 1
        collect_feed(name, channel, articles, cutoff, now, metrics)

    save_articles(output_file, articles)
    metrics["articles_saved"] = len(articles)


def calculate_status(metrics, run_error):
    """Final status: failed, partial, no_data or success."""
    if run_error is not None:
        return "failed"
    if metrics["feeds_succeeded"] == 0:
        return "failed"
    if metrics["feeds_failed"] or metrics["feeds_unsupported"]:
        return "partial"
    if metrics["articles_new"] == 0:
        return "no_data"
    return "success"


def print_summary(result, output_file):
    metrics = result["metrics"]
    details = result["details"]
    print("\nCollection summary")
    print(f"Run ID: {result['run_id']}")
    print(f"Status: {result['status']}")
    print(f"Feeds configured: {metrics['feeds_configured']}")
    print(f"Feeds attempted: {metrics['feeds_attempted']}")
    print(f"Feeds read successfully: {metrics['feeds_succeeded']}")
    print(f"Feeds failed: {metrics['feeds_failed']}")
    print(f"Feeds with unsupported format: {metrics['feeds_unsupported']}")
    print(
        f"Feeds skipped because of missing URL: {metrics['feeds_skipped_missing_url']}"
    )
    print(f"Total fetched RSS items: {metrics['items_fetched']}")
    print(f"Duplicate articles: {metrics['articles_duplicate']}")
    print(f"Rejected articles: {metrics['articles_rejected']}")
    print(f"Previously saved rows excluded: {metrics['existing_rows_removed']}")
    print(f"Total new articles: {metrics['articles_new']}")
    print(f"Total saved articles: {metrics['articles_saved']}")
    print(f"Saved to: {output_file}")
    print(f"Run time: {metrics['duration_seconds']:.2f} seconds")
    if details["run_error"]:
        print(f"Collection run error: {details['run_error']}", file=sys.stderr)


def run_collection(*, url, key, correlation_id=None, now=None, request=request_json):
    """Collect news and record the run in public.pipeline_runs.

    The run is created before any feed is read. If that fails,
    PipelineMonitoringError is raised and nothing is collected.
    """
    if not url or not key:
        raise ValueError("SUPABASE_URL and SUPABASE_KEY are required.")
    url = url.rstrip("/")
    started = perf_counter()
    now = now or datetime.now(UTC)
    metrics = empty_metrics()
    details = empty_details()
    sources_file = SOURCES_FILE
    output_file = OUTPUT_FILE

    run = create_pipeline_run(
        request,
        url=url,
        key=key,
        stage=STAGE,
        mode=MODE,
        correlation_id=correlation_id,
        metrics=metrics,
        details=details,
    )

    try:
        collect(sources_file, output_file, now, metrics, details)
    except (CollectionConfigError, CollectionSaveError) as error:
        details["run_error"] = str(error)
    except Exception as error:  # The run must always be finished.
        details["run_error"] = f"{type(error).__name__}: {error}"

    metrics["articles_rejected"] = (
        metrics["articles_rejected_missing_fields"] + metrics["articles_rejected_date"]
    )
    metrics["duration_seconds"] = round(perf_counter() - started, 3)
    status = calculate_status(metrics, details["run_error"])
    result = {
        "run_id": run["run_id"],
        "correlation_id": run["correlation_id"],
        "status": status,
        "metrics": metrics,
        "details": details,
        "monitoring_error": None,
    }

    try:
        finish_pipeline_run(
            request,
            url=url,
            key=key,
            run_id=run["run_id"],
            stage=STAGE,
            status=status,
            metrics=metrics,
            details=details,
        )
    except PipelineMonitoringError as error:
        details["monitoring_error"] = str(error)
        result["monitoring_error"] = str(error)
        print(f"Collection monitoring error: {error}", file=sys.stderr)

    print_summary(result, output_file)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Collect RSS news into data/news.csv and record the run."
    )
    parser.add_argument(
        "--correlation-id",
        help="Reuse the correlation ID of a related pipeline chain.",
    )
    args = parser.parse_args(argv)
    load_dotenv(ROOT / ".env")
    try:
        result = run_collection(
            url=os.getenv("SUPABASE_URL", "").strip(),
            key=os.getenv("SUPABASE_KEY", "").strip(),
            correlation_id=args.correlation_id,
        )
    except (PipelineMonitoringError, ValueError) as error:
        print(f"Collection monitoring error: {error}", file=sys.stderr)
        return 1
    return 1 if result["status"] == "failed" or result["monitoring_error"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
