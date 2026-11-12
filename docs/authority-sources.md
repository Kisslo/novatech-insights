# Authority feed registration — issue #52

## Sources

| Source name | Normalized key | Language | Feed |
|---|---|---|---|
| European Commission Digital Strategy | european commission digital strategy | en | https://digital-strategy.ec.europa.eu/en/rss.xml |
| IMY | imy | sv | https://www.imy.se/nyheter/rss/ |
| CERT-SE | cert-se | sv | https://www.cert.se/feed/rss.xml |
| European Data Protection Board | european data protection board | en | https://www.edpb.europa.eu/rss.xml_en |

## Coverage

- European Commission Digital Strategy: EU digital-policy news.
- IMY: Swedish data-protection news and guidance.
- CERT-SE: Swedish cybersecurity alerts and vulnerability information.
- European Data Protection Board: EU-level data-protection developments.

The additions broaden coverage through cybersecurity alerts and
EU-level data-protection information, rather than increasing source
count alone.

## Source identity

Use the exact source names above in data/sources.csv.
Generate comparison keys using the shared Python normalize_source helper.

The registry stores classifications, not per-source ranking weights.
Ranking parameters remain in configuration under issue #51.

## Feed validation

Feeds were fetched with the collector's User-Agent and parsed as RSS
with channel/item entries.

Date checks used collect_news.parse_date.
Seven-day eligibility used MAX_AGE_DAYS and UTC timestamps.

| Source | Validation date | Items | Valid title, link and date | Eligible within seven days |
|---|---|---:|---:|---:|
| European Commission Digital Strategy | 2026-11-11 | 10 | 10 | 1 |
| IMY | 2026-11-11 | 236 | 236 | 4 |
| CERT-SE | 2026-11-12 | 10 | 10 | 3 |
| European Data Protection Board | 2026-11-12 | 10 | 10 | 4 |

Counts are observations from those checks, not fixed expectations.
These checks did not write news.csv or Supabase.
Full-article fetching and the complete pipeline remain unverified.

## Registration and classification

- data/sources.csv includes all four feeds.
- The registry seed includes their display names and normalized keys.
- The seed test expects 34 sources.
- Seeding preserves existing names and classifications.
- Newly seeded sources initially have source_type = NULL.
- classify_authority_sources.sql sets the four named sources to authority.
- The classification script updates existing rows as well as new rows.
- It fails if any required source is missing.
- Other sources remain unchanged.
- Repeating classification is safe.

Mathias confirmed the authority classification for EU Digital Strategy
and IMY. CERT-SE and EDPB are proposed additions for review in PR #61.

## Local tests

The updated tests passed in novatech_source_registry_test:

- All 34 expected sources exist after seeding.
- Repeated seeding creates no duplicate source keys.
- Existing classifications survive seeding.
- Existing NULL and media classifications are changed to authority for
  the four specified sources.
- Other source records and the total row count are preserved.
- Repeating classification does not change the result.

All temporary test records and classifications were rolled back.
CI is configured to run both tests in both SQL test databases.
The latest revised changes still need commit, push and CI verification.

## Shared deployment plan

Coordinate deployment with Mathias and affected backend owners:

1. Check whether public.source_registry already exists.
2. Apply merged migration 009 only if the table is absent.
   If it exists, inspect its schema rather than blindly rerunning CREATE.
3. Apply the reviewed seed.
4. Apply the reviewed classification script.
5. Verify source records, classifications, RLS and backend read access.
6. Coordinate ranking integration and its configuration separately.

Migration 009, this updated seed and the classification script have
not been applied to shared Supabase in this work.

The Python collector reads data/sources.csv.
CSV changes do not automatically update public.rss_feeds.
Confirm whether an active workflow also needs the new feed records.
