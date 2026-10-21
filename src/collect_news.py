import csv
import urllib.request
import xml.etree.ElementTree as ET
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from http.client import HTTPException
from pathlib import Path
from urllib.error import URLError

FOLDER = Path(__file__).resolve().parent.parent / "data"
SOURCES_FILE = FOLDER / "sources.csv"
OUTPUT_FILE = FOLDER / "news.csv"

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


def main():
    now = datetime.now(UTC)
    cutoff = now - timedelta(days=MAX_AGE_DAYS)

    articles = {}
    removed_existing = 0

    # Check previously saved articles using the same date filter.
    if OUTPUT_FILE.exists():
        with OUTPUT_FILE.open("r", encoding="utf-8-sig", newline="") as file:
            for row in csv.DictReader(file):
                date = parse_date(row.get("published"))
                title = (row.get("title") or "").strip()
                link = (row.get("link") or "").strip()

                if not title or not link or date is None:
                    removed_existing += 1
                    continue

                if not cutoff <= date <= now:
                    removed_existing += 1
                    continue

                articles[link] = {
                    "title": title,
                    "link": link,
                    "source": row.get("source") or "",
                    "published": format_date(date),
                    "subject": row.get("subject") or "",
                    "description": row.get("description") or "",
                }

    # Load the source list.
    with SOURCES_FILE.open("r", encoding="utf-8-sig", newline="") as file:
        sources = list(csv.DictReader(file))

    total_new = 0

    for source in sources:
        name = source["name"].strip()
        feed_url = source["feed_url"].strip()

        if not feed_url:
            continue

        print(f"\nReading: {name}")

        request = urllib.request.Request(
            feed_url,
            headers={"User-Agent": "NovatechStudentRSS/1.0"},
        )

        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                root = ET.fromstring(response.read())
        except (URLError, OSError, HTTPException, ET.ParseError) as error:
            print(f"Could not read {name}: {error}")
            continue

        channel = root.find("channel")

        if channel is None:
            print("Skipped: this feed is not in the supported RSS format.")
            continue

        new_count = 0
        skipped_dates = 0
        descriptions_added = 0

        for item in channel.findall("item"):
            title = item.findtext("title", default="").strip()
            link = item.findtext("link", default="").strip()
            published = item.findtext("pubDate", default="").strip()
            description = clean_description(item.findtext("description", default=""))

            if not title or not link:
                continue

            # Fill missing descriptions without adding duplicate articles.
            # Preserve the existing title, date, source and subject.
            if link in articles:
                if description and not articles[link].get("description"):
                    articles[link]["description"] = description
                    descriptions_added += 1
                continue

            date = parse_date(published)

            if date is None or not cutoff <= date <= now:
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

        total_new += new_count
        print(f"New articles: {new_count}")
        print(f"Existing articles given descriptions: {descriptions_added}")
        print(f"Skipped because of date: {skipped_dates}")

    # Sort newest first and save through a temporary file.
    sorted_articles = sorted(
        articles.values(),
        key=lambda article: article["published"],
        reverse=True,
    )

    temporary_file = OUTPUT_FILE.with_suffix(".tmp")

    with temporary_file.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(sorted_articles)

    temporary_file.replace(OUTPUT_FILE)

    print(f"\nPreviously saved rows excluded: {removed_existing}")
    print(f"Total new articles: {total_new}")
    print(f"Total saved articles: {len(articles)}")
    print(f"Saved to: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
