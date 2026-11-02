import json
from pathlib import Path

articles = json.loads(
    Path("experiments/data/manual_review_articles.json").read_text(encoding="utf-8-sig")
)
labels = json.loads(
    Path("experiments/data/manual_review_pairs.json").read_text(encoding="utf-8-sig")
)

print("Artikelgrupper:", len(articles["groups"]))
print("Artikelposter:", sum(len(v) for v in articles["groups"].values()))
print("Manuella etiketter:", len(labels["pairs"]))
print("Samma händelse:", sum(p["label"] == "same_event" for p in labels["pairs"]))
print(
    "Olika händelser:", sum(p["label"] == "different_events" for p in labels["pairs"])
)
