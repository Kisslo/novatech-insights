import json
import re
from pathlib import Path

data = json.loads(
    Path("experiments/data/manual_review_articles.json").read_text(encoding="utf-8")
)

stopwords = {
    "the",
    "and",
    "for",
    "are",
    "with",
    "from",
    "that",
    "this",
    "into",
    "its",
    "how",
    "why",
    "you",
    "your",
    "not",
    "but",
    "has",
    "have",
    "was",
    "were",
    "can",
    "new",
    "their",
    "they",
    "about",
    "when",
    "who",
    "what",
    "just",
    "than",
    "still",
    "over",
    "too",
    "becoming",
    "built",
    "be",
    "to",
    "of",
    "in",
    "on",
    "a",
    "an",
    "is",
    "it",
    "at",
    "as",
    "by",
    "or",
    "this",
    "these",
    "those",
    "which",
    "while",
    "after",
    "more",
    "than",
    "also",
    "into",
    "through",
    "both",
    "being",
    "their",
}


def keywords(article):
    text = article["title"] + " " + article["description"]
    words = re.findall(r"[a-zA-Z0-9]+", text.casefold())
    return {w for w in words if len(w) > 3 and w not in stopwords}


for group_id in ("14", "16", "18"):
    a, b = data["groups"][group_id]
    words_a = keywords(a)
    words_b = keywords(b)
    shared = sorted(words_a & words_b)

    print(f"\nGRUPP {group_id}")
    print(f"Gemensamma ord ({len(shared)}): {', '.join(shared[:40])}")
