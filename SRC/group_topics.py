
import csv
import re
from pathlib import Path

PROJECT_FOLDER = Path(__file__).resolve().parent.parent
INPUT_FILE = PROJECT_FOLDER / "data" / "news_with_metadata.csv"
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
        "shares",
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
        "bolag",
        "företag",
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
        "AI agents and assistants",
        "AI automation and workflows",
        "AI and LLMs",
        "Software and APIs",
        "Cloud and DevOps",
        "Consumer Technology and Wearables",
        "Technology Events",
        "Startups and funding",
        "Business and Finance",
    ]

    for topic in priority_topics:
        keywords = TOPIC_KEYWORDS.get(topic, [])

        for keyword in keywords:
            if normalize(keyword) in full_text:
                return topic

    return "Other"


def main():
    if not INPUT_FILE.exists():
        raise FileNotFoundError(
            f"Input file not found: {INPUT_FILE}\n"
            "Run fetch_news_metadata.py first."
        )

    with INPUT_FILE.open(
        "r", encoding="utf-8-sig", newline=""
    ) as file:
        reader = csv.DictReader(file)
        fieldnames = reader.fieldnames or []
        articles = list(reader)

    required_columns = {"title", "subject", "description", "categories"}
    missing_columns = required_columns - set(fieldnames)

    if missing_columns:
        raise ValueError(
            f"Missing required columns: {', '.join(sorted(missing_columns))}"
        )

    for article in articles:
        article["subject"] = classify_topic(
            title=article.get("title", ""),
            description=article.get("description", ""),
            categories=article.get("categories", ""),
        )

    with OUTPUT_FILE.open(
        "w", encoding="utf-8-sig", newline=""
    ) as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(articles)

    topic_counts = {}
    for article in articles:
        topic = article["subject"]
        topic_counts[topic] = topic_counts.get(topic, 0) + 1

    print(f"Articles processed: {len(articles)}")
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
