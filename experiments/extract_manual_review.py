import json
import re
from pathlib import Path

report = Path("experiments/data/audit_result.txt").read_text(
    encoding="utf-16", errors="replace"
)
lines = report.splitlines()
wanted = {6, 9, 12, 14, 16, 17, 18}
groups = {}
current_group = None
in_articles = False
article = None
field = None

for line in lines:
    match = re.match(r"\s*Grupp\s+(\d+):", line)
    if match:
        current_group = int(match.group(1))
        in_articles = False
        article = None
        field = None
        if current_group in wanted:
            groups.setdefault(str(current_group), [])
        continue

    if current_group not in wanted:
        continue

    # Sluta läsa när rapporten går vidare till artikelpar.
    if "Artikelpar" in line:
        in_articles = False
        article = None
        field = None
        continue

    if re.match(r"\s*Artiklar:\s*$", line):
        in_articles = True
        article = None
        field = None
        continue

    if not in_articles:
        continue

    source_match = re.match(r"\s*K.{0,4}lla:\s*(.*)", line)
    title_match = re.match(r"\s*Rubrik:\s*(.*)", line)
    desc_match = re.match(r"\s*Beskrivning:\s*(.*)", line)

    if source_match:
        article = {
            "source": source_match.group(1).strip(),
            "title": "",
            "description": "",
            "published": "2026-10-20T12:00:00Z",
        }
        groups[str(current_group)].append(article)
        field = None
    elif title_match and article is not None:
        article["title"] = title_match.group(1).strip()
        field = "title"
    elif desc_match and article is not None:
        article["description"] = desc_match.group(1).strip()
        field = "description"
    elif article is not None and field and line.strip():
        article[field] += " " + line.strip()

errors = {
    group: len(articles)
    for group, articles in groups.items()
    if len(articles) != 2
}
missing = wanted - {int(group) for group in groups}

if missing or errors:
    print("Extraktionen är inte komplett.")
    print("Saknade grupper:", sorted(missing))
    print("Fel antal artiklar:", errors)
    raise SystemExit(1)

output_path = Path("experiments/data/manual_review_articles.json")
output_path.write_text(
    json.dumps({"groups": groups}, ensure_ascii=False, indent=2),
    encoding="utf-8",
)

print(f"Artikelunderlaget skapades: {output_path}")
for group, articles in groups.items():
    print(f"\nGrupp {group}:")
    for article in articles:
        print(f"  [{article['source']}] {article['title']}")
