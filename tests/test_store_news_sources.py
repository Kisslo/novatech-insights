import csv
from datetime import UTC, datetime

import pytest

import src.store_news as store_news


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("Reuters", "reuters"),
        ("reuters", "reuters"),
        ("Straße", "strasse"),
        ("STRASSE", "strasse"),
        ("\u00a0Reuters\u00a0", "reuters"),
    ],
)
def test_load_articles_normalizes_source_and_preserves_display(
    tmp_path, monkeypatch, source, expected
):
    csv_file = tmp_path / "news.csv"

    with csv_file.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=store_news.FIELDS)
        writer.writeheader()
        writer.writerow(
            {
                "title": "Test article",
                "link": "https://example.com/test",
                "source": source,
                "published": datetime.now(UTC).isoformat(),
                "subject": "",
                "description": "Test description",
            }
        )

    monkeypatch.setattr(store_news, "CSV_FILE", csv_file)

    articles = store_news.load_articles()

    assert len(articles) == 1
    assert articles[0]["source"] == source.strip()
    assert articles[0]["source_normalized"] == expected
