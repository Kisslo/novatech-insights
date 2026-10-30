import re
from pathlib import Path

path = Path("experiments/data/audit_result.txt")
text = path.read_text(encoding="utf-16", errors="replace")

print("Filstorlek:", path.stat().st_size, "bytes")
print("Antal tecken:", len(text))
print("Antal rader:", len(text.splitlines()))

print("\nMöjliga gruppmarkörer:")
for pattern in (
    r"(?im)^\s*Group\s+\d+",
    r"(?im)^\s*Grupp\s+\d+",
    r"(?im)^\s*GROUP\s+\d+",
):
    matches = re.findall(pattern, text)
    if matches:
        print(f"{pattern}: {len(matches)} träffar")

print("\nFörsta 35 raderna:")
for line in text.splitlines()[:35]:
    print(line[:240])
