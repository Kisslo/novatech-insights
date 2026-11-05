"""Load and validate configuration for topic ranking."""

import csv
import json
import math
from pathlib import Path

if __package__:
    from .source_normalization import normalize_source
else:
    from source_normalization import normalize_source

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = ROOT / "config" / "ranking.json"
DEFAULT_SOURCES_PATH = ROOT / "data" / "sources.csv"

_NUMERIC_FIELDS = (
    "half_life_days",
    "default_source_weight",
    "previous_days",
    "max_breadth_bonus",
    "breadth_scale",
    "max_velocity_bonus",
    "velocity_scale",
    "swedish_weight",
)
_POSITIVE_FIELDS = (
    "half_life_days",
    "previous_days",
    "breadth_scale",
    "velocity_scale",
)
_NON_NEGATIVE_FIELDS = (
    "default_source_weight",
    "max_breadth_bonus",
    "max_velocity_bonus",
    "swedish_weight",
)
_SOURCE_FIELDS = {"name", "feed_url", "language"}


def validate_ranking_config(config):
    if not isinstance(config, dict):
        raise ValueError("Ranking configuration must be a JSON object.")
    missing = [
        field for field in _NUMERIC_FIELDS + ("score_version",) if field not in config
    ]
    if missing:
        raise ValueError(f"Ranking configuration is missing: {', '.join(missing)}")
    if (
        not isinstance(config["score_version"], str)
        or not config["score_version"].strip()
    ):
        raise ValueError("score_version must be a non-empty string.")
    for field in _NUMERIC_FIELDS:
        value = config[field]
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
        ):
            raise ValueError(f"{field} must be a finite number.")
    for field in _POSITIVE_FIELDS:
        if config[field] <= 0:
            raise ValueError(f"{field} must be greater than zero.")
    for field in _NON_NEGATIVE_FIELDS:
        if config[field] < 0:
            raise ValueError(f"{field} must not be negative.")
    source_weights = config.get("source_weights", {})
    if not isinstance(source_weights, dict):
        raise ValueError("source_weights must be an object.")
    for source, weight in source_weights.items():
        if not isinstance(source, str) or not source.strip():
            raise ValueError("source_weights keys must be non-empty strings.")
        if (
            isinstance(weight, bool)
            or not isinstance(weight, (int, float))
            or not math.isfinite(weight)
            or weight < 0
        ):
            raise ValueError("source_weights values must be finite and non-negative.")


def load_ranking_config(
    config_path: Path = DEFAULT_CONFIG_PATH,
    sources_path: Path = DEFAULT_SOURCES_PATH,
) -> dict:
    """Load ranking settings and derive Swedish sources from the shared registry."""
    try:
        with config_path.open(encoding="utf-8") as file:
            config = json.load(file)
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"Could not read ranking configuration: {error}") from error

    validate_ranking_config(config)
    source_weights = config.get("source_weights", {})
    normalized_weights = {}
    for source, weight in source_weights.items():
        normalized_weights[normalize_source(source)] = weight

    swedish_sources = set()
    try:
        with sources_path.open(encoding="utf-8-sig", newline="") as file:
            reader = csv.DictReader(file)
            if not reader.fieldnames or not _SOURCE_FIELDS.issubset(reader.fieldnames):
                raise ValueError(
                    "Source registry must contain name, feed_url, and language."
                )
            for row in reader:
                if row.get("language", "").strip().casefold() == "sv":
                    source = normalize_source(row.get("name"))
                    if source:
                        swedish_sources.add(source)
    except (OSError, csv.Error, ValueError) as error:
        raise ValueError(f"Could not read source registry: {error}") from error

    result = dict(config)
    result["source_weights"] = normalized_weights
    result["swedish_sources"] = swedish_sources
    return result
