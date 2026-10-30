import json
import re
from pathlib import Path

path = Path("experiments/data/manual_review_articles.json")
data = json.loads(path.read_text(encoding="utf-8"))

def keywords(text):
    words = re.findall(r"[a-zA-Z0-9]+", text.casefold())
    stopwords = {
        "the", "and", "for", "are", "with", "from", "that", "this",
        "into", "its", "how", "why", "you", "your", "not", "but",
        "has", "have", "was", "were", "can", "new", "their", "they",
        "about", "when", "who", "what", "just", "than", "still",
        "over", "too", "becoming", "built", "be", "to", "of", "in",
        "on", "a", "an", "is", "it", "at", "as", "by", "or"
    }
    return {word for word in words if len(word) > 2 and word not in stopwords}

for group_id in ("14", "16", "18"):
    a, b = data["groups"][group_id]
    title_a = keywords(a["title"])
    title_b = keywords(b["title"])
    shared = sorted(title_a & title_b)

    print(f"\nGRUPP {group_id}")
    print(f"A: {a['title']}")
    print(f"B: {b['title']}")
    print(f"Gemensamma nyckelord: {shared or 'Inga'}")
