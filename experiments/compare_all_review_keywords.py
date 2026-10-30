import json
import re
from pathlib import Path

articles = json.loads(
    Path("experiments/data/manual_review_articles.json").read_text(encoding="utf-8")
)
labels = json.loads(
    Path("experiments/data/manual_review_pairs.json").read_text(encoding="utf-8-sig")
)

stopwords = {
    "the", "and", "for", "are", "with", "from", "that", "this",
    "into", "its", "how", "why", "you", "your", "not", "but",
    "has", "have", "was", "were", "can", "new", "their", "they",
    "about", "when", "who", "what", "just", "than", "still",
    "over", "too", "becoming", "built", "be", "to", "of", "in",
    "on", "a", "an", "is", "it", "at", "as", "by", "or",
    "these", "those", "which", "while", "after", "also", "being",
    "https", "http", "www", "com"
}

def keywords(article):
    text = article["title"] + " " + article["description"]
    words = re.findall(r"[a-zA-Z0-9]+", text.casefold())
    return {w for w in words if len(w) > 3 and w not in stopwords}

labels_by_group = {str(p["group"]): p for p in labels["pairs"]}

print("GRUPP | ETIKETT | GEMENSAMMA ORD")
print("-" * 70)

for group_id, pair_articles in articles["groups"].items():
    a, b = pair_articles
    shared = sorted(keywords(a) & keywords(b))
    label = labels_by_group[group_id]["label"]

    print(
        f"{group_id:>5} | {label:<16} | "
        f"{len(shared):>2} | {', '.join(shared[:20]) or 'Inga'}"
    )
