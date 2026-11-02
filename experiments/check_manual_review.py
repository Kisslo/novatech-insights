import json
from pathlib import Path

articles_path = Path("experiments/data/manual_review_articles.json")
labels_path = Path("experiments/data/manual_review_pairs.json")

articles = json.loads(articles_path.read_text(encoding="utf-8"))
labels = json.loads(labels_path.read_text(encoding="utf-8-sig"))

print("ANTAL MANUELLT GRANSKADE GRUPPER:", len(articles["groups"]))
print("ANTAL MANUELLA ETIKETTER:", len(labels["pairs"]))
print()

for pair in labels["pairs"]:
    group_id = str(pair["group"])
    group_articles = articles["groups"].get(group_id, [])
    print(
        f"Grupp {group_id}: "
        f"{len(group_articles)} artiklar | "
        f"{pair['label']} | "
        f"{pair['reason']}"
    )
