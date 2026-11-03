# News and Topics Data Contract

Last updated: 2026-11-03
Status: Draft for team review under issue #26 and PR #39.
Assessment and migration planning are recorded in PR #29.

This document distinguishes implemented behavior from remaining
team decisions. It does not apply database changes.

## Scope and implementation status

The target workflow is:

1. Collect and validate articles.
2. Store original article metadata in public.news.
3. Generate embeddings and group articles into topics.
4. Store article-topic relationships.
5. Calculate topic ranking scores.
6. Read ranked topics and their selected articles.
7. Generate topic labels and relevance explanations.

public.news already exists in Supabase.

Draft migrations 002–006 implement embedding storage, topics,
article-topic relationships, two read views, a group-saving
function and shared backend permissions.

All three GitHub CI checks passed on commit 0eb4cee:

- Ruff and pytest.
- PostgreSQL tests (0.8.2-pg17).
- PostgreSQL tests (pg17).

SQL tests cover topic counts, relationships, article selection,
row security, group saving and actual backend grants.
CI also tests with simulated Supabase default grants.

src/group_news.py reads articles and groups them locally.
Saving requires the explicit --save option. Each group is
saved through public.save_topic_group(bigint[]) in a separate
REST API request.

Migrations 002–006 have not been applied to Supabase.
Live REST API access, existing-data preservation and the
complete workflow still require deployment verification.

An article can belong to several topics.
Use public.topic_articles for membership, not news.topic_id.

The earlier news_articles.news_id, categorized_at and
content_articles design is superseded as the Week 44 target.
Existing dependencies must still be checked before any retirement.

The current label reader produces Markdown output.
Saving generated labels back to topics is not implemented
in this workflow. Article generation and generated-output
database storage remain outside this PR's scope.

## References

- [Collected-news schema](../sql/001_create_news.sql)
- [Embedding storage](../sql/002_create_topic_storage.sql)
- [Topics and article links](../sql/003_create_topics_and_links.sql)
- [Read views](../sql/004_create_topic_read_views.sql)
- [Group-saving function](../sql/005_save_topic_group.sql)
- [Backend permissions](../sql/006_topic_backend_permissions.sql)
- [Verification results](topic-storage-verification.md)
- [Collector](../src/collect_news.py)
- [Uploader](../src/store_news.py)
- [Grouping and optional saving](../src/group_news.py)
- [Topic labels and top-N reader](../src/label_topics.py)
- [Issue #26](https://github.com/Kisslo/novatech-insights/issues/26): storage and read interface.
- [PR #29](https://github.com/Kisslo/novatech-insights/pull/29): assessment and migration plan.
- [PR #39](https://github.com/Kisslo/novatech-insights/pull/39): draft implementation.
- [Issue #19](https://github.com/Kisslo/novatech-insights/issues/19): embeddings and grouping.
- [Issue #35](https://github.com/Kisslo/novatech-insights/issues/35): ranking.
- [Issue #27](https://github.com/Kisslo/novatech-insights/issues/27): labels and top-N output.
- [Issue #36](https://github.com/Kisslo/novatech-insights/issues/36): integration verification.
- [Issue #37](https://github.com/Kisslo/novatech-insights/issues/37): feedback.
- [Issue #38](https://github.com/Kisslo/novatech-insights/issues/38): README updates.

## Collected articles: public.news

Data owns original metadata and publisher RSS descriptions.

| Column | PostgreSQL type | Rule |
|---|---|---|
| id | bigint | Generated identity primary key. |
| title | text | Required and non-blank. |
| link | text | Required, non-blank and unique. |
| source | text | Required; uploader rejects blank values. |
| published | timestamptz | Required publication time. |
| subject | text | Legacy field; not authoritative topic membership. |
| description | text | Publisher RSS description; empty string allowed. |
| collected_at | timestamptz | First database insertion time; defaults to now(). |
| embedding | extensions.vector(384) | Nullable addition in migration 002; not deployed to Supabase. |

The eight original columns are NOT NULL.
subject and description default to empty strings.
collected_at is database insertion time, not RSS retrieval time.

Keep original metadata unchanged during grouping and ranking.
Generated labels and explanations must not replace RSS descriptions.

### Embeddings

Turker confirmed:

- Model: paraphrase-multilingual-MiniLM-L12-v2.
- Dimensions: 384.
- Input: article title and RSS description.

Migration 002 adds extensions.vector(384).
NULL means no embedding is stored; it does not distinguish
unprocessed articles from failed attempts.

The grouping program calculates embeddings locally.
The --save option stores topic memberships, not embeddings.

Before completing embedding persistence, agree:

- Model and input version tracking.
- Detection of changed input and outdated embeddings.
- Failure handling and regeneration rules.
- Consistent input construction across embedding consumers.
- Extension version and schema in the deployment environment.
- Required permissions for storing or updating embeddings.

The current grouping input combines the title and description.
When no description is available, it uses the title alone.

Turker owns embedding generation and grouping under #19.
Nosheen owns the agreed storage and constraints under #26.

## Topic storage: public.topics

Migration 003 implements public.topics.
The schema remains subject to team review.

| Field | PostgreSQL type | Purpose |
|---|---|---|
| id | bigint | Generated identity primary key. |
| score | double precision | Calculated ranking score. |
| score_calculated_at | timestamptz | Time the score was calculated. |
| score_version | text | Ranking formula version. |
| score_breakdown | jsonb | Signals and their contributions. |
| label | text | Intended storage for a generated topic headline. |
| why_relevant_sv | text | Intended storage for a Swedish relevance explanation. |
| llm_relevance | smallint | Intended storage for an AI relevance rating from 1 to 5. |

All fields except id may be NULL, subject to the constraints below.

Implemented constraints:

- label and why_relevant_sv must be non-blank when supplied.
- llm_relevance must be an integer from 1 to 5 when supplied.
- score must be finite when supplied.
- score_version must be non-blank when supplied.
- score_breakdown must be a JSON object when supplied.
- The four score fields must either all be NULL or all be non-NULL.

Ranking owns the four score fields under #35.
New topics created by save_topic_group start without scores or labels.

Nedal's label reader under #27 currently writes generated labels,
explanations and relevance ratings to Markdown output.
It does not write them back to public.topics.

Use llm_relevance instead of the earlier name relevance.
Whether it contributes to score remains an open decision under #35.

The team still needs to review:

- The implemented field types and integer-only relevance rating.
- Score scale, refresh rules and score_breakdown structure.
- Handling of failed or incomplete scoring and labelling.
- Topic identity and regrouping rules.
- Label and score freshness when article content changes.
- Any future label writeback behavior and permissions.

Earlier suggestions such as velocity, swedish_signal, first_seen,
last_seen and status are not implemented as separate columns.

## Article-topic linking table: public.topic_articles

Migration 003 implements public.topic_articles.

| Field | Requirement |
|---|---|
| news_id | NOT NULL bigint referencing public.news(id). |
| topic_id | NOT NULL bigint referencing public.topics(id). |

The composite primary key is (topic_id, news_id).
Neither field is individually unique.

For example, article 101 may link to topics 5 and 8.
The pair (topic_id = 5, news_id = 101) must not be stored twice.

References to missing articles or topics are rejected.
Both foreign keys use ON DELETE RESTRICT.
Articles and topics with existing memberships cannot be deleted.

This behavior is tested locally and in CI.
Team review of regrouping and retention rules remains pending.

Similarity is not stored.
Its meaning, scale and update rules must be agreed if added.

rank_in_topic is calculated by the read view, not stored here.

## Saving groups

Migration 005 defines:

public.save_topic_group(p_news_ids bigint[]) RETURNS bigint

The function accepts existing news.id values and returns the
saved or reused topic ID.

### Input and identity

- Input must be a non-empty, one-dimensional array.
- IDs must be positive and not NULL.
- At least two distinct article IDs are required.
- Input IDs are deduplicated and sorted.
- Missing article references cause the save to fail.
- Group identity is the complete set of distinct article IDs.

Saving the same set again reuses an existing topic.
Changing input order or repeating an ID does not create a new topic.

If the article-ID set changes and no exact match exists,
the function creates a new topic.

Existing topics and memberships are not automatically replaced,
retired or deleted. Older and overlapping groups may remain.

The team must agree how these groups should be handled.

### Atomicity and metadata

A new topic and all its article links are saved in one transaction.
A failed save leaves no partial topic or membership records
from that call.

Reusing a topic preserves its labels and score fields.
The function does not update original news metadata.

The function validates IDs and relationships.
It does not enforce semantic similarity, source diversity
or a publication-date window. The grouping program determines
which articles belong together.

### Concurrent writers

Calls use a transaction-level advisory lock.
Membership writers must follow the same locking convention
by using this function.

Direct inserts can bypass that convention.
Parallel-session concurrency has not yet been tested.

### Python and REST API integration

src/group_news.py remains read-only unless --save is supplied.

With --save, it sends a POST request to:

/rest/v1/rpc/save_topic_group

The JSON request contains p_news_ids with all distinct IDs
from the complete group.

The program uses SUPABASE_URL and SUPABASE_KEY.
The secret key is sent only in the apikey header.

Display limits do not limit the groups or memberships saved.
Each group uses a separate request and transaction.

If saving fails, the program stops processing later groups.
Earlier groups may already be committed.

A connection failure can leave the outcome of the current
request uncertain. Repeating the same article-ID set reuses
a successfully saved topic under the function's identity rules.

Python tests use fake API responses.
A live Supabase REST API save has not yet been verified.

## Ranked-topic read interface

Migration 004 implements the two read views.

### public.topic_overview

Returns one row per topic with:

- id
- label
- why_relevant_sv
- llm_relevance
- score
- article_count
- source_count

Counts include all articles linked to the topic, before selecting
the displayed articles. No publication-date filter is applied
inside this view.

Empty topics remain visible with zero counts.
The reader filters article_count > 0 before selecting top topics.

### public.topic_top_articles

Returns up to three articles per topic with:

- topic_id
- rank_in_topic
- news_id
- title
- source
- link
- description

Original article metadata and news.id are preserved.
rank_in_topic is calculated when reading, not stored.

### Article selection

The confirmed Week 44 rule is:

1. Prefer articles with a non-empty description.
2. Keep the best article from each source.
3. Prefer newer publication dates.
4. Use smaller news_id values to break remaining ties.
5. Return up to three articles per topic.

The implementation treats whitespace-only descriptions as empty.
This clarification remains documented for team review.

Both source selection and final article ranking use description
presence, publication date descending and news_id ascending.

Sources are compared using their stored source values.
No source-name normalization is performed by these views.

Readers must explicitly order selected articles by topic_id
and rank_in_topic.

### Topic selection and counts

The Week 44 target is up to 20 topics.
The reader controls the topic limit and explicit topic ordering.

The current label reader skips topics without scores and
topics without articles before applying its topic limit.

Select the ranked topics before expanding their article rows.
Do not apply the topic limit to joined article rows.

For example, a topic containing four articles from two sources
displays two articles, one per source. Its counts remain:

- article_count = 4
- source_count = 2

Topic ranking tie-breaking, eligibility and freshness rules
still need alignment across grouping, ranking and reading.

Similarity is not stored or used by these views.

### View permissions and row security

Both views use security_invoker = true.
Readers need the appropriate view and underlying table permissions.

Row-security behavior depends on the reader's database role.
Ordinary roles are subject to applicable RLS policies.
The shared service_role bypasses RLS but still needs SQL grants.

Full-topic counts require access to all relevant linked rows.

Local and CI tests verify view access, underlying table access
and reader row-security behavior.

## Backend access

Migration 006 defines grants for service_role.

### Confirmed ranking requirements

The ranking owner confirmed on 2026-11-02 that ranking plans
to use the Supabase REST API with SUPABASE_URL and SUPABASE_KEY.

Ranking requires:

- SELECT on public.news, public.topic_articles and public.topics.
- UPDATE on score, score_calculated_at, score_version and
  score_breakdown in public.topics.
- No INSERT or DELETE for ranking itself.

At confirmation time, the ranking connection was not implemented.
Its live integration still requires verification.

### Grouping and reader requirements

The grouping owner confirmed that the original grouping
implementation only needed SELECT on public.news.
It processed groups locally without saving them.

PR #39 adds optional group saving through --save.
This requires the saving function and its underlying write grants.

The label reader reads topic_overview and topic_top_articles.
It does not require label updates or deletion permissions
for its current Markdown-output workflow.

### Implemented shared grants

| Object | Grants to service_role |
|---|---|
| public schema | USAGE |
| public.news | SELECT added; existing permissions preserved |
| public.topics | SELECT and INSERT |
| public.topic_articles | SELECT and INSERT |
| public.topic_overview | SELECT |
| public.topic_top_articles | SELECT |
| public.topics_id_seq | USAGE |
| public.save_topic_group(bigint[]) | EXECUTE |
| Four ranking columns in public.topics | UPDATE |

Migration 006 does not remove existing news permissions.
It resets service_role grants on the new topic objects before
applying the grants listed above.

No UPDATE grant is provided for existing labels or memberships.
No DELETE grant is provided for topics or memberships.

The saving function uses SECURITY INVOKER.
The caller therefore needs underlying INSERT permissions.
Those table-level INSERT grants also permit direct inserts,
including initial topic field values allowed by the constraints.
They do not enforce function-only writes.

All programs using service_role share the same permissions.
Ranking, grouping and the reader are not isolated from each other.

Migrations 003–005 remove automatic grants from PUBLIC and
existing anon, authenticated and service_role roles on the
new topic objects. Migration 006 adds the backend grants.
It does not add topic access for anon or authenticated.

If service_role does not exist, migration 006 reports that
its grants were skipped. CI creates the role before testing
the actual backend grants.

### Permission verification

Tests using the actual migration grants verify that the backend:

- Reads news.
- Saves and reuses complete groups.
- Updates the four ranking fields.
- Reads both views and their full topic counts.
- Cannot update existing labels.
- Cannot update memberships.
- Cannot delete topics or memberships.

The test role is a non-superuser with BYPASSRLS.
Test records are rolled back.
Migration grants remain in the local test databases.

These results do not establish live Supabase API access.

## Article identity and duplicates

Use news.id as the shared article identifier.
Do not assume IDs from different tables refer to the same article.

IDs remain stable while records exist in this database.
They are not portable across databases or deletion and reinsertion.

The uploader trims surrounding whitespace from links, keeps the
first valid input record for each repeated link and skips links
already stored. Existing database metadata is preserved.

The grouping program performs additional local URL and title
normalization and deduplication. It preserves the selected
article's existing database ID.

This local processing does not rewrite stored links, delete
database duplicates or establish a new database-wide identity rule.

Source identity also needs alignment: grouping compares normalized
source names, while the read views compare stored source values.

CSV input has no database ID. Resolve it using the exact stored
link and verify the resulting news.id.

Once news_id is available, preserve it instead of repeatedly
matching articles by link.

## Dates and collection window

published is publication time, not collection or insertion time.

Exchange timezone-aware UTC timestamps, for example:

2026-10-28T08:00:00Z

The collector accepts supported RSS or ISO dates and converts
them to UTC. Missing, invalid, timezone-free and future dates
are rejected rather than invented.

The collector retains articles within the seven days preceding
the start of its run, including the boundaries. It also checks
previously saved CSV rows.

The uploader independently validates a seven-day window.

The grouping fetch applies a lower publication-date cutoff
of seven days before its run. Group construction also limits
the publication-date span within a group to seven days.

These processing windows are not database retention policies.
Stored articles and topics are not automatically deleted.
The read views do not apply a publication-date window.

## RSS descriptions and CSV exchange

CSV columns remain:

title,link,source,published,subject,description

Use UTF-8 with BOM and a header row.
Python readers should use utf-8-sig and a CSV parser.

The collector removes HTML formatting, preserves common text
boundaries, decodes HTML character references and normalizes
whitespace in RSS descriptions.

Descriptions are publisher input, not generated summaries or
verified full article text. Missing descriptions become empty
strings. Article pages are not fetched to fill them.

The collector can fill missing CSV descriptions from feeds.
The uploader skips existing links, so CSV enrichment does not
automatically update existing database rows.

Missing descriptions must not cause Content reading to fail.
The current grouping input uses the title when a description
is missing.

## Legacy data and migration

Preserve existing news, news_articles and rss_feeds data.

Legacy categories and news.subject do not establish membership
in the new topic model. Do not automatically convert them.

news_articles.summary must not replace news.description.

Inspect readers, writers and dependencies before changing legacy
storage. Historical inspection counts must be refreshed before
migration.

Do not:

- Assume matching numeric IDs across tables.
- Invent missing publication dates.
- Delete unmatched records without explicit approval.
- Drop legacy tables through this draft implementation.

PR #29 records assessment and migration planning.
PR #39 contains the draft implementation and verification.

## Access and verification

Use backend credentials stored in environment variables or
deployment secrets. Never commit them or expose them in frontend code.

RLS is enabled on news and on the new topics and topic_articles
tables. Backend SQL grants are defined in migration 006.
A view does not automatically provide appropriate access control.

Local and CI verification covers:

- Valid embedding dimensions and allowed missing embeddings.
- Multiple topics per article.
- Rejection of duplicate pairs and invalid references.
- Correct counts before article display limits.
- Article selection and ordering.
- Exact-set group reuse and preservation of topic metadata.
- Rollback of failed group saves.
- Reader row-security behavior.
- Actual backend permissions and denied operations.
- Python request construction and simulated API failures.

Remaining integration verification includes:

- Preservation of existing production articles and IDs.
- Live Supabase REST API reads and saves.
- Grouping-to-ranking-to-reader integration.
- Handling of stale scores, labels and older groups.
- Deployment compatibility and migration procedure.

See topic-storage-verification.md for test evidence and limitations.

Local and CI test results do not establish production deployment.

## Remaining decisions and checks

The storage schema, read views, group-saving function, optional
Python saving and shared backend grants are implemented and
tested in draft PR #39.

The following items remain:

- Team review of table names, field types, defaults and nullability.
- Confirmation of the integer-only llm_relevance contract.
- Embedding metadata, persistence and regeneration rules.
- Treatment of changed, overlapping and older groups.
- Review of ON DELETE RESTRICT for linked articles and topics.
- Whether similarity should be stored and used in future.
- Team review of whitespace-only descriptions being treated as empty.
- Topic ranking tie-breaking, eligibility and time windows.
- Source identity and normalization rules.
- Scoring and labelling freshness and failure behavior.
- Review of shared service_role grants and direct INSERT access.
- Parallel-session testing of concurrent group saves.
- Supabase compatibility and preservation of existing data.
- Live integration with grouping, ranking and the Content reader.
- Usage documentation and PR description updates.
- Migration review, deployment responsibility and procedure.

Issue #26 remains open until its agreed scope and verification
are complete. PR #39 remains Draft.
Migrations 002–006 have not been applied to Supabase.