from urllib.parse import parse_qs, urlencode, urlparse

import pytest

import src.backfill_source_normalization as backfill


def test_read_only_checks_all_pages_without_writing(monkeypatch):
    pages = {
        0: [
            {"id": 1, "source": "Stra\u00dfe", "source_normalized": None},
            {"id": 2, "source": "STRASSE", "source_normalized": "strasse"},
        ],
        2: [
            {
                "id": 3,
                "source": "\u00a0Reuters\u00a0",
                "source_normalized": None,
            },
            {"id": 4, "source": None, "source_normalized": None},
            {"id": 5, "source": " \t", "source_normalized": ""},
        ],
        5: [],
    }
    requested_cursors = []

    def fake_request(url, key, method="GET", payload=None):
        assert method == "GET"
        assert payload is None

        query = parse_qs(urlparse(url).query)
        cursor = int(query["id"][0].removeprefix("gt."))
        requested_cursors.append(cursor)

        return pages[cursor]

    monkeypatch.setattr(backfill, "request_json", fake_request)

    result = backfill.backfill_sources(
        "https://example.supabase.co",
        "test-key",
    )

    assert requested_cursors == [0, 2, 5]
    assert result == {
        "scanned": 5,
        "needs_update": 3,
        "updated": 0,
    }


def test_apply_updates_only_keys_and_guards_original_values(monkeypatch):
    articles = [
        {"id": 1, "source": "Stra\u00dfe", "source_normalized": None},
        {"id": 2, "source": "Reuters", "source_normalized": "WRONG"},
        {"id": 3, "source": "STRASSE", "source_normalized": "strasse"},
    ]
    updates = []

    def fake_request(url, key, method="GET", payload=None):
        query = parse_qs(urlparse(url).query)

        if method == "GET":
            if query["id"] == ["gt.0"]:
                return articles

            assert query["id"] == ["gt.3"]
            return []

        assert method == "PATCH"
        assert query["select"] == ["id,source,source_normalized"]
        updates.append((query, payload))

        if query["id"] == ["eq.1"]:
            assert query["source"] == ["eq.Stra\u00dfe"]
            assert query["source_normalized"] == ["is.null"]
            assert payload == {"source_normalized": "strasse"}

            return [
                {
                    "id": 1,
                    "source": "Stra\u00dfe",
                    "source_normalized": "strasse",
                }
            ]

        assert query["id"] == ["eq.2"]
        assert query["source"] == ["eq.Reuters"]
        assert query["source_normalized"] == ["eq.WRONG"]
        assert payload == {"source_normalized": "reuters"}

        return [
            {
                "id": 2,
                "source": "Reuters",
                "source_normalized": "reuters",
            }
        ]

    monkeypatch.setattr(backfill, "request_json", fake_request)

    result = backfill.backfill_sources(
        "https://example.supabase.co",
        "test-key",
        apply=True,
    )

    assert len(updates) == 2
    assert result == {
        "scanned": 3,
        "needs_update": 2,
        "updated": 2,
    }
    assert articles[0]["source"] == "Stra\u00dfe"
    assert articles[1]["source"] == "Reuters"


def test_apply_stops_when_update_matches_no_row(monkeypatch):
    methods = []

    def fake_request(url, key, method="GET", payload=None):
        methods.append(method)

        if method == "GET":
            return [
                {
                    "id": 1,
                    "source": "Reuters",
                    "source_normalized": None,
                }
            ]

        return []

    monkeypatch.setattr(backfill, "request_json", fake_request)

    with pytest.raises(RuntimeError, match="matched no visible row"):
        backfill.backfill_sources(
            "https://example.supabase.co",
            "test-key",
            apply=True,
        )

    assert methods == ["GET", "PATCH"]


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, "is.null"),
        ("", "eq."),
        ("WIRED", "eq.WIRED"),
        ("Stra\u00dfe", "eq.Stra\u00dfe"),
        ('A"B\\C', 'eq.A"B\\C'),
        ("A&B + C, D.(E):F", "eq.A&B + C, D.(E):F"),
        ("\tReuters\n", "eq.\tReuters\n"),
    ],
)
def test_filters_preserve_values_through_url_encoding(value, expected):
    filtered = backfill.equality_filter(value)

    assert filtered == expected

    query = urlencode({"source": filtered})
    decoded = parse_qs(query)

    assert decoded["source"] == [expected]


def test_missing_normalized_field_stops_before_writing(monkeypatch):
    def fake_request(url, key, method="GET", payload=None):
        assert method == "GET"
        return [{"id": 1, "source": "Reuters"}]

    monkeypatch.setattr(backfill, "request_json", fake_request)

    with pytest.raises(RuntimeError, match="missing required fields"):
        backfill.backfill_sources(
            "https://example.supabase.co",
            "test-key",
            apply=True,
        )
