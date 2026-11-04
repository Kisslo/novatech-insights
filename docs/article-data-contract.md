# News and Topics Data Contract

Last updated: 2026-11-04

Issue: #26
Implementation: PR #39
Assessment and migration planning: PR #29

This document describes the current implementation and its limitations.
It does not apply database changes.

## Current status

- Migrations 002–006 have not been applied to Supabase.
- Local tests passed for article selection, Unicode source keys,
  function-only group inserts, ranking updates and label updates.
- Python tests passed: 21 grouping tests, 5 storage-normalization tests
  and 5 backfill tests.
- Ruff passed for the changed Python files.
- Latest confirmed pushed commit: a8f979f.
- All three CI checks passed on that historical commit.
- The newer changes still require final validation, commit, push and CI.
- No merge has been confirmed.

Turker has said no additional review is needed before merging once the
agreed changes are complete and checks pass. Live Supabase verification
must happen before deployment or production use.

Old-topic handling was accepted as a separate follow-up. A later review
also proposed last_seen_at and status; neither is implemented, and the
scope of those additions still needs agreement.

## Workflow and responsibilities

The target workflow is:

1. Collect and validate articles.
2. Store article metadata in public.news.
3. Generate embeddings and group related articles.
4. Save topics and article-topic memberships.
5. Calculate and save ranking scores.
6. Read ranked topics and selected articles.
7. Generate and save labels and relevance information.

Storage provides the tables, constraints, saving function and read views.
The ranking module calculates scores. The label module generates labels,
Swedish explanations and relevance ratings.

This PR grants label-update permissions. Label writeback application
code is planned in a separate PR.

An article can belong to several topics. Use public.topic_articles,
not news.topic_id.

## References

- [Collected-news schema](../sql/001_create_news.sql)
- [Embedding and source-key storage](../sql/002_create_topic_storage.sql)
- [Topics and memberships](../sql/003_create_topics_and_links.sql)
- [Read views](../sql/004_create_topic_read_views.sql)
- [Group-saving function](../sql/005_save_topic_group.sql)
- [Backend permissions](../sql/006_topic_backend_permissions.sql)
- [Shared source normalization](../src/source_normalization.py)
- [Uploader](../src/store_news.py)
- [Grouping and optional saving](../src/group_news.py)
- [Source-key backfill](../src/backfill_source_normalization.py)
- [Verification notes](topic-storage-verification.md)
- [Issue #26](https://github.com/Kisslo/novatech-insights/issues/26)
- [PR #29](https://github.com/Kisslo/novatech-insights/pull/29)
- [PR #39](https://github.com/Kisslo/novatech-insights/pull/39)

## Articles: public.news

Preserve the existing article IDs and original metadata.

| Column | Purpose |
|---|---|
| id | Generated bigint identity primary key. |
| title | Required, nonblank article title. |
| link | Required, nonblank, unique article link. |
| source | Display source name; uploader rejects blank values. |
| published | Publication timestamp. |
| subject | Legacy field, not authoritative topic membership. |
| description | Publisher RSS description; may be empty. |
| collected_at | First database insertion time. |
| embedding | Nullable extensions.vector(384), added by migration 002. |
| source_normalized | Nullable text comparison key with COLLATE "C", added by migration 002. |

Generated summaries and labels must not replace RSS descriptions.

### Embeddings

Intended model: paraphrase-multilingual-MiniLM-L12-v2.

- Dimensions: 384.
- Input: title and RSS description; title alone when description is absent.
- NULL means no embedding is stored.
- Grouping currently calculates embeddings locally.
- Group saving does not persist embeddings.

Model/input version tracking, persistence, regeneration and failure
handling remain separate integration concerns.

### Shared source normalization

The shared Python function is:

    normalize_source(source) = (source or "").strip().casefold()

The uploader stores the result in source_normalized. Grouping uses the
same helper for source comparisons.

Examples:

| Display source | Stored comparison key |
|---|---|
| Reuters | reuters |
| reuters | reuters |
| Straße | strasse |
| STRASSE | strasse |
| Reuters surrounded by nonbreaking spaces | reuters |
| Missing or whitespace-only source | empty string |

The source field retains display spelling and case. The uploader
continues its existing trimming of surrounding whitespace.

SQL views use the stored key directly. They do not attempt to reproduce
Python Unicode normalization using lower() or btrim().

COLLATE "C" provides exact comparison of the stored keys.

NULL source_normalized means that normalization has not been completed.
An empty string means the source was missing or blank.

Every writer that inserts articles or changes source must also maintain
source_normalized using the shared rule. A missing or stale key can
produce incorrect source counts or article selection.

The CSV format is unchanged; source_normalized is derived in Python.

### Existing-row backfill

The uploader skips existing links, so rerunning it does not normalize
existing database rows.

src/backfill_source_normalization.py scans all visible news rows:

- Default mode is read-only.
- --apply explicitly enables updates.
- Only source_normalized is updated.
- Original source names, IDs and other metadata are preserved.
- Correct keys are skipped.
- Pagination uses increasing article IDs.
- Each update checks the ID, original source and previously read key.
- A changed or inaccessible row stops the run rather than silently
  reporting a successful update.
- Each update is a separate request; earlier updates may remain saved
  if a later request fails.
- A rerun skips keys that are already correct.

The script uses SUPABASE_URL and SUPABASE_KEY. The key is sent in the
apikey header.

The backfill tests use fake API responses. No live backfill has run.

Before production use, verify that the backfill can see all required
rows and has permission to update source_normalized. Migration 006
preserves existing news grants; it does not add this UPDATE permission.

Coordinate article writers while backfilling, then verify that required
rows have correct keys before relying on the new views.

## Topics: public.topics

| Column | Purpose |
|---|---|
| id | Generated bigint identity primary key. |
| label | Generated topic headline. |
| why_relevant_sv | Swedish relevance explanation. |
| llm_relevance | Integer relevance rating from 1 to 5. |
| score | Finite ranking score. |
| score_calculated_at | Timestamp of score calculation. |
| score_version | Nonblank ranking-formula version. |
| score_breakdown | JSON object containing scoring details. |

Metadata may be NULL, subject to these constraints:

- Supplied labels and explanations must not be blank.
- Supplied relevance must be between 1 and 5.
- Supplied scores must be finite.
- Supplied score_version must not be blank.
- Supplied score_breakdown must be a JSON object.
- The four ranking fields must all be NULL or all be non-NULL.

The ranking module owns the four ranking values. Whether llm_relevance
contributes to score remains a ranking decision.

New groups start without labels or scores.

No last_seen_at, retirement flag or status column is implemented.

## Memberships: public.topic_articles

| Column | Rule |
|---|---|
| topic_id | Required bigint referencing topics.id. |
| news_id | Required bigint referencing news.id. |

The composite primary key is (topic_id, news_id).

An article may belong to multiple topics. Duplicate pairs and missing
references are rejected.

Both foreign keys use ON DELETE RESTRICT. Linked topics and articles
cannot be deleted while memberships remain.

Similarity and article display rank are not stored here.

## Saving groups

Migration 005 defines:

    public.save_topic_group(p_news_ids bigint[]) RETURNS bigint

The function:

- Requires a nonempty, one-dimensional array.
- Rejects NULL or nonpositive IDs.
- Requires at least two distinct article IDs.
- Deduplicates and sorts IDs.
- Reuses a topic with exactly the same complete article-ID set.
- Preserves labels and scores when reusing a topic.
- Creates a new topic when no exact-set match exists.
- Saves a new topic and all memberships atomically.
- Rolls back its writes when a reference or other operation fails.

The function validates IDs and relationships. It does not enforce
semantic similarity, source diversity or a publication-date window.

### Function-only backend inserts

The function uses SECURITY DEFINER and search_path = pg_catalog.
Application tables are schema-qualified.

In the verified local database, the function and topic tables are owned
by postgres. Before deployment, verify the trusted function owner,
ownership privileges and EXECUTE grants in Supabase.

Calls acquire pg_advisory_xact_lock(260039, 1).

service_role has no direct INSERT permission on topics or topic_articles
and no direct USAGE grant on topics_id_seq from migration 006.
Backend group creation must therefore use the saving function.

Database owners and administrators remain privileged. This restriction
is for the application backend role.

Parallel-session concurrency testing remains outstanding.

### Python saving

src/group_news.py is read-only unless --save is supplied.

Saving sends complete article-ID sets to:

    /rest/v1/rpc/save_topic_group

Each group uses a separate REST request and transaction. If a later
group fails, earlier groups may remain committed.

A connection failure can leave the current request's outcome uncertain.
Retrying the same article-ID set reuses an already-saved exact group.

Display limits do not truncate the memberships saved.

## Read views

Both views use security_invoker = true. Readers need appropriate
permissions on the views and underlying tables.

service_role bypasses RLS but still requires SQL grants.

### public.topic_overview

Returns:

- id
- label
- why_relevant_sv
- llm_relevance
- score
- article_count
- source_count

Counts include all linked articles, before display selection.
There is no publication-date or lifecycle filter.

Empty topics remain visible with zero counts.

source_count counts distinct nonempty source_normalized values.
NULL and empty keys do not contribute to source_count.

### public.topic_top_articles

Returns:

- topic_id
- rank_in_topic
- news_id
- title
- source
- link
- description

Returns at most three articles per topic, with at most one article per
normalized source.

Selection order:

1. Description present before missing or whitespace-only description.
2. Newer publication date; NULL dates last.
3. Smaller news_id for remaining ties.

The same ordering chooses each source's representative and ranks the
remaining articles within the topic.

NULL and empty source keys share one selection bucket. One article from
that bucket may be selected, although it does not increase source_count.

Original source names remain available for display.

Readers must explicitly order by topic_id and rank_in_topic.

Rerunning migration 004 revokes view grants. Reapply migration 006
afterward in local tests to restore backend view access.

## Ranking and top-N reading

Ranking can read topic_overview for metadata and counts.

For complete article inputs, read topic_articles together with news.
Do not use topic_top_articles as a substitute for all member articles.

Suggested article fields are id, title, description, source,
source_normalized, published and link. The ranking owner determines
which inputs the calculation requires.

Ranking may update:

- score
- score_calculated_at
- score_version
- score_breakdown

Send all four values together in one update per topic. This is the
proposed first-version approach; no ranking batch RPC is implemented.

save_topic_group does not save ranking values.

For top-N presentation, select eligible topics before expanding their
article rows. Do not apply the topic limit to joined article rows.

The target is up to 20 topics, with the top five available for Telegram.
The team still needs to agree on eligibility, freshness and ordering
ties. Exclude unscored topics when requesting a scored ranking.

## Backend permissions

All programs using service_role share these permissions.

| Object | Grants from migration 006 |
|---|---|
| public schema | USAGE |
| news | SELECT added; existing grants preserved |
| topics | SELECT |
| topic_articles | SELECT |
| topic_overview | SELECT |
| topic_top_articles | SELECT |
| save_topic_group(bigint[]) | EXECUTE |
| Four ranking columns in topics | UPDATE |
| label, why_relevant_sv, llm_relevance in topics | UPDATE |

No direct INSERT on topic tables, membership UPDATE or topic/membership
DELETE is granted.

Migration 006 resets service_role grants on the new topic objects before
applying these grants. It does not add topic access for anon or
authenticated.

If service_role is absent, migration 006 reports that its grants were
skipped.

Local permission tests verify:

- Direct topic and membership inserts are denied.
- Function-based saving and exact-set reuse work.
- Ranking updates work.
- Both views and full counts can be read.
- Label, explanation and relevance updates work.
- Label writeback preserves ranking values.
- Blank labels/explanations and out-of-range relevance are rejected.
- Group reuse preserves labels and scores.
- Membership updates and topic/membership deletes are denied.

The test role is a non-superuser with BYPASSRLS. Test records roll back.

These SQL tests do not establish live REST API access.

## Topic lifecycle

Changed article-ID sets can create new topics. Existing groups are not
automatically updated, retired or deleted.

There is currently no authoritative way to identify current versus
retired topics. A non-NULL label does not establish freshness.

Old-topic handling was accepted as a follow-up. A later review proposed:

- last_seen_at updated on both creation and exact-set reuse.
- A status field supporting the Telegram workflow.

Neither is implemented. last_seen_at alone would not retire overlapping
older groups. Required filters, time windows and status transitions still
need agreement.

The seven-day grouping window is not a retention or retirement policy.

## Article identity, dates and CSV exchange

Use news.id as the shared article identifier. IDs from other tables are
not interchangeable.

The uploader preserves existing rows when links conflict. Grouping's
local deduplication does not delete database rows or rewrite links.

published is publication time. collected_at is first database insertion
time. Exchange timezone-aware UTC timestamps.

The collector and uploader validate a seven-day article window.
Grouping fetches recent articles and limits a group's publication-date
span. Read views do not apply that window.

CSV columns remain:

    title,link,source,published,subject,description

Use UTF-8 with BOM, a header row and a CSV parser. Python readers use
utf-8-sig.

Descriptions are publisher RSS input, not generated summaries or
verified full article text. Missing descriptions remain empty; grouping
can use the title alone.
## Required source keys after backfill

Migration 007_require_normalized_sources.sql makes source_normalized
NOT NULL. It must run only after the backfill has completed and its
results have been verified.

Production deployment order:

1. Apply migrations 002–006 under the agreed migration plan.
2. Ensure all article writers maintain the shared Python-normalized key.
3. Run the backfill and verify the stored keys.
4. Confirm that this query returns zero:

       SELECT count(*)
       FROM public.news
       WHERE source_normalized IS NULL;

5. Apply migration 007.
6. Verify API behavior before enabling ranking and Telegram readers.

The NULL-count check verifies completeness, not normalization correctness.

After migration 007, an INSERT that omits source_normalized or an UPDATE
that sets it to NULL fails. No default is supplied.

An empty string remains valid for a missing or blank source name.
The constraint does not detect incorrect keys or source-name changes
that leave an old key unchanged.

The planned pasted-article API must also supply the normalized key.
For source = 'kisslo', the comparison key is 'kisslo'.

Local testing confirmed that valid keys save, missing keys are rejected
and NULL updates are rejected. Test records were rolled back.

CI applies migration 007 after the earlier SQL tests and checks the
constraint in both test databases. This does not perform a production
backfill.

## Deployment and existing-data safeguards

Preserve news, news_articles and rss_feeds, including existing IDs.

Legacy subject/category values do not establish topic membership.
news_articles.summary must not replace news.description.

Do not:

- Rerun migration 001 against the existing production news table.
- Drop or clear legacy tables as part of this work.
- Assume matching IDs across tables.
- Invent missing publication dates.
- Run setup_supabase_permission_test.sql in real Supabase.

setup_supabase_permission_test.sql is LOCAL/CI ONLY.

Migration order for a fresh test database is 001 followed by 002–006.
Production already has news; its reviewed plan must start from the
actual existing schema rather than rerunning 001.

The revised migration 002 adds both embedding and source_normalized.
Do not blindly rerun it in a local database that already has embedding.
The existing local test database received the new source column
separately.

Before production use:

1. Verify the existing schema, dependencies and data-preservation plan.
2. Confirm migration ownership, extension compatibility and permissions.
3. Apply the agreed migrations.
4. Verify complete article visibility and backfill UPDATE access.
5. Check and apply source normalization under coordinated writer activity.
6. Verify stored keys and all article writers.
7. Verify REST reads, group saves, label/ranking updates and read views.
8. Test the grouping-to-ranking-to-reader workflow.

Keep credentials in environment variables or deployment secrets.
Never commit or expose actual keys in frontend code.

## Remaining work and limitations

Before merging the current changes:

- Update remaining comments and verification notes.
- Resolve the scope of the later lifecycle/status review comments.
- Complete relevant final checks and inspect the diff.
- Commit, push and confirm CI for the final commit.
- Mark the PR ready and merge according to repository requirements.

Before production use:

- Verify migrations and permissions against Supabase.
- Run and verify the existing-row backfill.
- Verify preservation of existing data.
- Verify live REST and complete pipeline integration.

Separate integration concerns include embedding persistence and tracking,
label writeback application code, topic lifecycle, freshness rules and
any future Telegram status workflow.

Merging PR #39 does not by itself establish production readiness or
complete all requirements of issue #26.