
import csv
import ssl
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

import certifi

PROJECT_FOLDER = Path(__file__).resolve().parent.parent
NEWS_FILE = PROJECT_FOLDER / "data" / "news.csv"


class MetaParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.descriptions = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() != "meta":
            return

        attrs = dict(attrs)
        name = attrs.get("name", "").lower()
        prop = attrs.get("property", "").lower()

        if name == "description" or prop == "og:description":
            content = attrs.get("content", "").strip()
            if content:
                self.descriptions.append((name or prop, content))


def main():
    with NEWS_FILE.open(
        "r", encoding="utf-8-sig", newline=""
    ) as file:
        rows = [
            row for row in csv.DictReader(file)
            if row["source"].strip().lower() == "techcrunch"
        ]

    if not rows:
        print("Inga TechCrunch-artiklar hittades.")
        return

    url = rows[0]["link"]
    context = ssl.create_default_context(cafile=certifi.where())
    request = urllib.request.Request(
        url, headers={"User-Agent": "Mozilla/5.0"}
    )

    with urllib.request.urlopen(
        request, context=context, timeout=30
    ) as response:
        page = response.read().decode("utf-8", errors="replace")
        print("Status:", response.status)
        print("Artikel:", response.url)

    parser = MetaParser()
    parser.feed(page)

    for name, description in parser.descriptions:
        print(f"\n{name}:")
        print(description)


if __name__ == "__main__":
    main()
