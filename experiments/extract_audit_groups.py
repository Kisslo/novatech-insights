import json
import re
from pathlib import Path

text = Path("experiments/data/audit_result.txt").read_text(
    encoding="utf-16",
    errors="replace",
)
lines = text.splitlines()

group_starts = [
    i for i, line in enumerate(lines)
    if re.match(r"^\s*Grupp\s+\d+:", line, re.IGNORECASE)
]

groups = []

for position, start in enumerate(group_starts):
    end = (
        group_starts[position + 1]
        if position + 1 < len(group_starts)
        else len(lines)
    )
    block = lines[start:end]

    header_match = re.search(
        r"Grupp\s+(\d+):\s*(\d+)\s+artiklar",
        block[0],
    )
    if not header_match:
        continue

    group_id = int(header_match.group(1))
    expected_count = int(header_match.group(2))

    articles = []
    current = None
    in_articles_section = False

    for line in block[1:]:
        if re.match(r"^\s*Artiklar:\s*$", line):
            in_articles_section = True
            continue

        if re.match(
            r"^\s*Artikelpar,\s*från\s+lägst\s+till\s+högst\s+likhet:",
            line,
            re.IGNORECASE,
        ):
            break

        if not in_articles_section:
            continue

        source_match = re.match(r"^\s*Källa:\s*(.*)", line)
        title_match = re.match(r"^\s*Rubrik:\s*(.*)", line)
        description_match = re.match(r"^\s*Beskrivning:\s*(.*)", line)
        url_match = re.match(r"^\s*Länk:\s*(.*)", line)

        if source_match:
            if current:
                articles.append(current)
            current = {
                "source": source_match.group(1).strip(),
                "title": "",
                "description": "",
                "url": "",
            }

        elif current and title_match:
            current["title"] = title_match.group(1).strip()

        elif current and description_match:
            current["description"] = description_match.group(1).strip()

        elif current and url_match:
            current["url"] = url_match.group(1).strip()

    if current:
        articles.append(current)

    groups.append({
        "group_id": group_id,
        "reported_article_count": expected_count,
        "extracted_article_count": len(articles),
        "articles": articles,
    })

output = Path("experiments/data/audit_groups_for_review.json")
output.write_text(
    json.dumps(
        {
            "description": (
                "Extracted article listings from audit_result.txt. "
                "Titles and descriptions are not manually verified."
            ),
            "groups": groups,
        },
        ensure_ascii=False,
        indent=2,
    ),
    encoding="utf-8",
)

mismatches = [
    group for group in groups
    if group["reported_article_count"] != group["extracted_article_count"]
]

print("Grupper extraherade:", len(groups))
print("Artikelposter extraherade:", sum(
    len(group["articles"]) for group in groups
))
print("Grupper med avvikande antal:", len(mismatches))

for group in mismatches:
    print(
        f"Grupp {group['group_id']}: "
        f"rapporten anger {group['reported_article_count']}, "
        f"extraherade {group['extracted_article_count']}"
    )

print("Uppdaterad fil:", output)
