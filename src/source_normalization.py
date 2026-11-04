"""Shared source-name normalization for storage and grouping."""


def normalize_source(source: str | None) -> str:
    """Trim surrounding Unicode whitespace and ignore case."""
    return (source or "").strip().casefold()
