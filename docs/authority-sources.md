# Authority feed registration — issue #52

## Sources

| Source name | Normalized key | Language | Feed |
|---|---|---|---|
| European Commission Digital Strategy | european commission digital strategy | en | https://digital-strategy.ec.europa.eu/en/rss.xml |
| IMY | imy | sv | https://www.imy.se/nyheter/rss/ |

The European Commission feed covers EU digital-policy news.
IMY is Sweden's Integritetsskyddsmyndigheten.

Use these exact source names in collection and the shared Python
normalize_source helper to generate their comparison keys.

## Validation — 2026-11-11

Both feeds were fetched using the collector's User-Agent and parsed
as RSS with channel/item entries.

| Source | Items | Valid title, link and date | Eligible within seven days |
|---|---:|---:|---:|
| European Commission Digital Strategy | 10 | 10 | 1 |
| IMY | 236 | 236 | 4 |

Date validation used collect_news.parse_date.
Eligibility used the collector's MAX_AGE_DAYS and UTC timestamps.
Counts are observations from this validation, not fixed expectations.

These checks read the feeds without writing news.csv or Supabase.
They do not verify full-article fetching or the complete pipeline.

## Registration

- data/sources.csv contains the two feed entries.
- sql/seed_source_registry.sql includes their names and normalized keys.
- The seed test expects all 32 registered sources.
- Existing seed entries and classifications are preserved.
- source_type remains NULL pending agreed classification criteria.
- Ranking parameters belong to configuration under issue #51.

## Deployment status

Migration 009 and the updated seed have not been applied to shared
Supabase in this work.

The Python collector reads data/sources.csv.
Adding CSV entries does not update public.rss_feeds automatically.
Confirm whether an active workflow also needs those feed records.