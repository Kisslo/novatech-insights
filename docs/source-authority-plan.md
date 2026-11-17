# Source registry for source-type-based ranking

Status: Draft PR #56. Classification criteria still need agreement.

## Goal

Store source names and classifications for ranking integration.

## Table: public.source_registry

| Column | Purpose |
|---|---|
| source_normalized | Primary key matching news.source_normalized. |
| name | Source name for display. |
| source_type | media, authority or NULL when not classified. |

## Rules

- Use the shared Python normalize_source helper for comparison keys.
- Source keys and display names must not be blank.
- Source keys must be unique.
- Only media, authority and NULL are allowed as source types.
- The seed registers the 30 existing sources without classifying them.
- Repeating the seed preserves existing names and classifications.
- Preserve existing news, rss_feeds and article IDs.
- Do not require every article source to exist in this table.
- Give service_role read access; registry writes remain administrative.
- Do not store per-source authority weights in this table.

## Ranking integration

Mathias confirmed that ranking will use source_type for a higher base
weight and an exponentially decaying start bonus.

The parameters belong in the ranking configuration.
The registry itself does not calculate scores or change ranking behavior.

The current ranking code still reads config/ranking.json.
Reading source classifications from the database requires integration.

## Decisions still needed

- Criteria for classifying a source as media or authority.
- Who classifies sources and maintains those classifications.
- How ranking handles NULL classifications and unknown sources.
- Final ranking parameters and integration behavior.

## Validation

- Test the migration and constraints locally.
- Verify backend read-only permissions.
- Run the seed twice and assert that all 30 expected sources exist.
- Check that no duplicate source keys are created.
- Verify that existing classifications remain unchanged.
- Roll back temporary test classifications.
- Run the SQL tests in both CI test databases.

## Deployment

The earlier draft was applied only to local Docker PostgreSQL.
The revised migration and both SQL tests passed locally in
novatech_source_registry_test. Seed test classifications were rolled back.
CI validation of the revised changes is pending.

Migration 009 has not been applied to shared Supabase.
Coordinate shared deployment after review.