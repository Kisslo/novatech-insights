import json
from pathlib import Path

import pytest

from ranking_config import load_ranking_config


def test_loads_settings_and_derives_swedish_sources(tmp_path):
    config = tmp_path / "ranking.json"
    config.write_text(
        '{"half_life_days": 3, "default_source_weight": 1.0, '
        '"previous_days": 6, "max_breadth_bonus": 1.0, "breadth_scale": 3.0, '
        '"max_velocity_bonus": 1.0, "velocity_scale": 5.0, '
        '"swedish_weight": 0.5, "score_version": "test", '
        '"source_weights": {" Reuters ": 2.0}}',
        encoding="utf-8",
    )
    sources = tmp_path / "sources.csv"
    sources.write_text(
        "name,feed_url,language\nReuters,https://example.test,en\n"
        "  Breakit  ,https://example.test,SV\n",
        encoding="utf-8",
    )

    result = load_ranking_config(Path(config), Path(sources))

    assert result["source_weights"] == {"reuters": 2.0}
    assert result["swedish_sources"] == {"breakit"}


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("half_life_days", 0),
        ("previous_days", -1),
        ("breadth_scale", float("inf")),
        ("velocity_scale", 0),
        ("default_source_weight", -0.1),
        ("max_breadth_bonus", float("nan")),
        ("swedish_weight", -1),
    ],
)
def test_rejects_invalid_numeric_settings(tmp_path, field, value):
    config = {
        "half_life_days": 3,
        "default_source_weight": 1.0,
        "previous_days": 6,
        "max_breadth_bonus": 1.0,
        "breadth_scale": 3.0,
        "max_velocity_bonus": 1.0,
        "velocity_scale": 5.0,
        "swedish_weight": 0.5,
        "score_version": "test",
        "source_weights": {},
    }
    config[field] = value
    config_path = tmp_path / "ranking.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    sources_path = tmp_path / "sources.csv"
    sources_path.write_text("name,feed_url,language\nA,https://a.test,en\n")

    with pytest.raises(ValueError, match=field):
        load_ranking_config(config_path, sources_path)


def test_rejects_source_registry_without_required_columns(tmp_path):
    config_path = tmp_path / "ranking.json"
    config_path.write_text(
        '{"half_life_days": 3, "default_source_weight": 1, '
        '"previous_days": 6, "max_breadth_bonus": 1, "breadth_scale": 3, '
        '"max_velocity_bonus": 1, "velocity_scale": 5, "swedish_weight": 0.5, '
        '"score_version": "test", "source_weights": {}}',
        encoding="utf-8",
    )
    sources_path = tmp_path / "sources.csv"
    sources_path.write_text("name,feed_url\nA,https://a.test\n", encoding="utf-8")

    with pytest.raises(ValueError, match="name, feed_url, and language"):
        load_ranking_config(config_path, sources_path)
