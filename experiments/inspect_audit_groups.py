import re
from pathlib import Path

text = Path("experiments/data/audit_result.txt").read_text(
    encoding="utf-16",
    errors="replace",
)

lines = text.splitlines()
group_indexes = [
    i for i, line in enumerate(lines)
    if re.match(r"^\s*Grupp\s+\d+:", line, re.IGNORECASE)
]

print(f"Antal grupper hittade: {len(group_indexes)}")

for index in group_indexes:
    print("\n" + "=" * 75)
    for line in lines[index:index + 7]:
        print(line[:220])
