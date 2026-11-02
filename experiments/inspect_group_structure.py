import re
from pathlib import Path

text = Path("experiments/data/audit_result.txt").read_text(
    encoding="utf-16",
    errors="replace",
)
lines = text.splitlines()

starts = [
    i
    for i, line in enumerate(lines)
    if re.match(r"^\s*Grupp\s+\d+:", line, re.IGNORECASE)
]

for index in starts[:2]:
    print("\n" + "=" * 80)
    end = min(index + 35, len(lines))
    for number in range(index, end):
        print(f"{number + 1:4}: {lines[number]}")
