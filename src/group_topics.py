import argparse
import csv
import re
from pathlib import Path

PROJECT_FOLDER = Path(__file__).resolve().parent.parent
INPUT_FILE = PROJECT_FOLDER / "data" / "news.csv"
OUTPUT_FILE = PROJECT_FOLDER / "data" / "news_with_topics.csv"


TOPIC_KEYWORDS = {
    "AI and LLMs": [
        "artificial intelligence",
        "generative ai",
        "language model",
        "large language model",
        "llm",
        "ai model",
        "machine learning",
        "deep learning",
        "neural network",
        "foundation model",
        "frontier model",
        "voice ai",
        "ai-powered",
        "ai pages",
        "ai sidor",
        "ai sida",
        "ai-powered feature",
        "ai regulation",
        "ai tools",
        "edge devices",
        "identify animals",
        "construction blueprints",
        "blueprints ai",
    ],
    "AI agents and assistants": [
        "ai agent",
        "ai agents",
        "agentic",
        "ai assistant",
        "personal ai assistant",
        "autonomous agent",
        "n8n agents",
    ],
    "AI automation and workflows": [
        "automation",
        "automate",
        "automated",
        "workflow",
        "workflows",
        "n8n",
        "pr process",
        "public relations",
        "communications",
    ],
    "Software and APIs": [
        "api",
        "software engineering",
        "developer tools",
        "programming",
        "open source",
        "code generation",
        "coding",
        "app development",
        "android app",
        "google play",
        "vibe-coded",
        "orbital computing",
        "satellites",
    ],
    "Cloud and DevOps": [
        "devops",
        "cloud computing",
        "cloud infrastructure",
        "deployment",
        "data center",
        "data centre",
    ],
    "Cybersecurity": [
        "cybersecurity",
        "cyber security",
        "hacking",
        "hacked",
        "hackades",
        "data breach",
        "security flaw",
        "infiltrated",
        "cyberattack",
        "recording device",
        "spying",
        "avlyssning",
        "avlyssna",
        "dold inspelningsenhet",
        "frysar",
        "trade secrets",
        "enterprise security",
        "security teams",
        "security holes",
        "cybersecurity teams",
    ],
    "Startups and funding": [
        "startup",
        "startups",
        "funding",
        "investment",
        "raises",
        "raised",
        "venture capital",
        "series a",
        "series b",
        "funding round",
        "plockar in nya miljoner",
        "tar in färska miljoner",
        "battlefield 200",
    ],
    "Robotics and autonomous systems": [
        "robot",
        "robots",
        "robotics",
        "self-driving",
        "autonomous vehicle",
        "autonomous car",
    ],
    "Consumer Technology and Wearables": [
        "smartwatch",
        "smart watch",
        "wearable",
        "wearables",
        "smart ring",
        "fitbit",
        "pixel watch",
        "smart home",
        "smart glasses",
    ],
    "Technology Events": [
        "techcrunch disrupt",
        "conference",
        "tech event",
    ],
    "Energy and Climate Technology": [
        "fusion power",
        "fusion energy",
        "blast furnace",
        "emissions",
        "climate technology",
        "renewable energy",
        "lithium",
    ],
    "Business and Finance": [
        "revenue",
        "acquisition",
        "acquires",
        "stock market",
        "stock exchange",
        "listed on the stock exchange",
        "fintech",
        "salary",
        "salaries",
        "billion kronor",
        "million kronor",
        "förvärv",
        "börsen",
        "aktier",
        "storägare",
        "fond",
        "miljoner",
        "miljarder",
        "lön",
        "lönerna",
    ],
}


def normalize(text):
    """Normalize text for case-insensitive keyword matching."""
    text = (text or "").lower()
    return re.sub(r"[^a-z0-9åäöæøéüß]+", " ", text).strip()


def classify_topic(title, description="", categories=""):
    """Classify an article using its title, description, and RSS categories."""
    full_text = normalize(f"{title} {description} {categories}")

    priority_topics = [
        "Cybersecurity",
        "Robotics and autonomous systems",
        "Energy and Climate Technology",
        "Cloud and DevOps",
        "AI agents and assistants",
        "AI and LLMs",
        "AI automation and workflows",
        "Software and APIs",
        "Consumer Technology and Wearables",
        "Technology Events",
        "Startups and funding",
        "Business and Finance",
    ]

    for topic in priority_topics:
        keywords = TOPIC_KEYWORDS.get(topic, [])

        for keyword in keywords:
            if re.search(
                rf"(?<!\w){re.escape(normalize(keyword))}(?!\w)",
                full_text,
            ):
                return topic

    return "Other"


def main():
    parser = argparse.ArgumentParser(description="Classify news articles by topic.")
    parser.add_argument(
        "--reclassify",
        action="store_true",
        help="Reclassify all articles, including those with an existing subject.",
    )
    args = parser.parse_args()

    if not INPUT_FILE.exists():
        raise FileNotFoundError(f"Input file not found: {INPUT_FILE}")

    with INPUT_FILE.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        fieldnames = reader.fieldnames or []
        articles = list(reader)

    required_columns = {
        "title",
        "link",
        "source",
        "published",
        "subject",
    }
    missing_columns = required_columns - set(fieldnames)

    if missing_columns:
        raise ValueError(
            f"Missing required columns: {', '.join(sorted(missing_columns))}"
        )

    # Support older input files that do not yet have descriptions.
    output_fieldnames = list(fieldnames)
    if "description" not in output_fieldnames:
        output_fieldnames.append("description")

    classified_count = 0
    preserved_count = 0

    for article in articles:
        article["description"] = article.get("description") or ""
        existing_subject = (article.get("subject") or "").strip()

        # Preserve existing assignments during normal runs.
        if existing_subject and not args.reclassify:
            preserved_count += 1
            continue

        article["subject"] = classify_topic(
            title=article.get("title", ""),
            description=article["description"],
        )
        classified_count += 1

    with OUTPUT_FILE.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=output_fieldnames,
        )
        writer.writeheader()
        writer.writerows(articles)

    topic_counts = {}
    for article in articles:
        topic = (article.get("subject") or "").strip() or "(empty)"
        topic_counts[topic] = topic_counts.get(topic, 0) + 1

    print(f"Articles classified: {classified_count}")
    print(f"Existing subjects preserved: {preserved_count}")
    print(f"Total articles: {len(articles)}")
    print(f"Output saved to: {OUTPUT_FILE}")
    print("\nArticles per topic:")

    for topic, count in sorted(
        topic_counts.items(),
        key=lambda item: item[1],
        reverse=True,
    ):
        print(f"{topic}: {count}")


if __name__ == "__main__":
    main()
