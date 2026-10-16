import csv
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

FOLDER = Path(__file__).resolve().parent.parent/"data"
SOURCES_FILE = FOLDER / "sources.csv"
OUTPUT_FILE = FOLDER / "news.csv"

FIELDS = ["title", "link", "source", "published", "subject"]

# Load articles already saved.
articles = {}

if OUTPUT_FILE.exists():
    with OUTPUT_FILE.open("r", encoding="utf-8-sig", newline="") as file:
        for row in csv.DictReader(file):
            row.setdefault("subject", "")
            articles[row["link"]] = row

# Load the list of RSS sources.
with SOURCES_FILE.open("r", encoding="utf-8-sig", newline="") as file:
    sources = list(csv.DictReader(file))

total_new = 0

# Collect news from each source.
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

        channel = root.find("channel")

        if channel is None:
            print("Skipped: this feed is not in the supported RSS format.")
            continue

        new_count = 0

        for item in channel.findall("item"):
            title = item.findtext("title", default="").strip()
            link = item.findtext("link", default="").strip()
            published = item.findtext("pubDate", default="").strip()

            if not title or not link or link in articles:
                continue

            articles[link] = {
                "title": title,
                "link": link,
                "source": name,
                "published": published,
                "subject": "",
            }
            new_count += 1

        total_new += new_count
        print(f"New articles: {new_count}")

    except Exception as error:
        print(f"Could not read {name}: {error}")
        continue

# Save all articles, including those from previous runs.
with OUTPUT_FILE.open("w", encoding="utf-8-sig", newline="") as file:
    writer = csv.DictWriter(file, fieldnames=FIELDS)
    writer.writeheader()
    writer.writerows(articles.values())

print(f"\nTotal new articles: {total_new}")
print(f"Total saved articles: {len(articles)}")
print(f"Saved to: {OUTPUT_FILE}")