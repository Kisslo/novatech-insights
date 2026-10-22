
import csv
import html
import re
import ssl
import time
import urllib.request
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from pathlib import Path

import certifi

PROJECT_FOLDER = Path(__file__).resolve().parent.parent
DATA_FOLDER = PROJECT_FOLDER / "data"

NEWS_FILE = DATA_FOLDER / "news.csv"
SOURCES_FILE = DATA_FOLDER / "sources.csv"
OUTPUT_FILE = DATA_FOLDER / "news_with_metadata.csv"

USER_AGENT = "NovatechStudentRSS/1.0"
SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())


def clean_text(value):
    if not value:
        return ""

    value = html.unescape(value)
    value = re.sub(r"<[^>]+>", " ", value)
    return " ".join(value.split())


def get_child_text(element, field_name):
    for child in element:
        if child.tag.rsplit("}", 1)[-1] == field_name:
            return "".join(child.itertext()).strip()
    return ""


def fetch_feed(url):
    request = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT},
    )

    with urllib.request.urlopen(
        request, context=SSL_CONTEXT, timeout=30
    ) as response:
        root = ET.fromstring(response.read())

    items = root.findall("./channel/item")
    if not items:
        items = root.findall(".//{*}entry")

    return items


class MetaParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.description = ""

    def handle_starttag(self, tag, attrs):
        if tag.lower() != "meta" or self.description:
            return

        attrs = dict(attrs)
        name = attrs.get("name", "").lower()
        prop = attrs.get("property", "").lower()

        if name == "description" or prop == "og:description":
            self.description = clean_text(attrs.get("content", ""))


def fetch_article_description(url):
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0"},
    )

    with urllib.request.urlopen(
        request, context=SSL_CONTEXT, timeout=20
    ) as response:
        page = response.read().decode("utf-8", errors="replace")

    parser = MetaParser()
    parser.feed(page)
    return parser.description


def main():
    if not NEWS_FILE.exists() or not SOURCES_FILE.exists():
        raise FileNotFoundError(
            "Kontrollera att data/news.csv och data/sources.csv finns."
        )

    with NEWS_FILE.open(
        "r", encoding="utf-8-sig", newline=""
    ) as file:
        reader = csv.DictReader(file)
        original_fields = reader.fieldnames or []
        articles = list(reader)

    if "link" not in original_fields:
        raise ValueError("news.csv måste innehålla kolumnen 'link'.")

    metadata = {
        article.get("link", "").strip(): {
            "description": "",
            "categories": "",
        }
        for article in articles
        if article.get("link", "").strip()
    }

    with SOURCES_FILE.open(
        "r", encoding="utf-8-sig", newline=""
    ) as file:
        sources = list(csv.DictReader(file))

    # Hämta metadata från RSS-flödena.
    for source in sources:
        name = source.get("name", "").strip()
        feed_url = source.get("feed_url", "").strip()

        if not feed_url:
            continue

        print(f"\nLäser RSS: {name}")

        try:
            items = fetch_feed(feed_url)
            matched = 0

            for item in items:
                link = get_child_text(item, "link")

                if not link:
                    for child in item:
                        if child.tag.rsplit("}", 1)[-1] == "link":
                            link = child.attrib.get("href", "")
                            if link:
                                break

                link = link.strip()
                if link not in metadata:
                    continue

                description = (
                    get_child_text(item, "description")
                    or get_child_text(item, "summary")
                    or get_child_text(item, "encoded")
                    or get_child_text(item, "content")
                )

                categories = [
                    clean_text(child.text or "")
                    for child in item
                    if child.tag.rsplit("}", 1)[-1] == "category"
                    and clean_text(child.text or "")
                ]

                metadata[link] = {
                    "description": clean_text(description),
                    "categories": "; ".join(dict.fromkeys(categories)),
                }
                matched += 1

            print(f"Artiklar matchade i RSS: {matched}")

        except Exception as error:
            print(f"Kunde inte läsa {name}: {error}")

    # För artiklar utan beskrivning: testa artikelsidan.
    missing = [
        link for link, data in metadata.items()
        if not data["description"]
    ]

    print(f"\nArtiklar som behöver reservhämtning: {len(missing)}")

    for index, link in enumerate(missing, start=1):
        try:
            description = fetch_article_description(link)
            metadata[link]["description"] = description

            status = "Beskrivning hittad" if description else "Ingen beskrivning"
            print(f"[{index}/{len(missing)}] {status}: {link}")

        except Exception as error:
            print(f"[{index}/{len(missing)}] Kunde inte hämta artikel: {link}")
            print(f"  Orsak: {error}")

        time.sleep(0.5)

    output_fields = original_fields + [
        field for field in ("description", "categories")
        if field not in original_fields
    ]

    with OUTPUT_FILE.open(
        "w", encoding="utf-8-sig", newline=""
    ) as file:
        writer = csv.DictWriter(file, fieldnames=output_fields)
        writer.writeheader()

        for article in articles:
            link = article.get("link", "").strip()
            extra = metadata.get(link, {})
            article["description"] = extra.get("description", "")
            article["categories"] = extra.get("categories", "")
            writer.writerow(article)

    with_description = sum(
        bool(data["description"]) for data in metadata.values()
    )

    with_categories = sum(
        bool(data["categories"]) for data in metadata.values()
    )

    print("\n--- Sammanfattning ---")
    print(f"Artiklar totalt: {len(articles)}")
    print(f"Artiklar med beskrivning: {with_description}")
    print(f"Artiklar med kategorier: {with_categories}")
    print(f"Resultat sparat i: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
