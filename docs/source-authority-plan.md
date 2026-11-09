# Source authority storage proposal

Status: Draft proposal for team review.

## Goal

Store source information that ranking can use later.

## Proposed table: public.source_registry

| Column | Purpose |
|---|---|
| source_normalized | Primary key matching news.source_normalized. |
| name | Source name for display. |
| source_type | Optional category; NULL until classified. |
| authority_weight | Optional ranking weight; NULL until agreed. |

## Rules

- Use the existing Python normalize_source helper for comparison keys.
- Source keys and display names must not be blank.
- Source keys must be unique.
- A supplied source_type must not be blank.
- A supplied authority_weight must be finite and non-negative.
- Initially register the 30 existing sources without assigning types or weights.
- Preserve existing news, rss_feeds and article IDs.
- Do not require every article source to exist in this table.
- Give service_role read access; registry writes remain administrative.

## Ranking integration

Current ranking reads weights from config/ranking.json.
Creating this table alone will not change ranking behavior.

The team must agree on:
- Source categories and classifications.
- Weight values.
- How database weights interact with configuration weights.
- How ranking handles unknown or unweighted sources.

## Validation

Test the migration locally before shared Supabase deployment.