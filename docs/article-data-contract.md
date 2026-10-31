# News and Topics Data Contract

Status: Draft for team review under issue #26 and PR #39.
Assessment and migration planning are tracked in PR #29.

This document describes the Week 44 target and distinguishes it
from implemented functionality. It does not apply database changes.

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
Draft migrations 002–004 implement embedding storage, topics,
article-topic relationships and the two read views.

The views and their count and article-selection tests passed
locally. Both GitHub CI jobs passed on commit e9ba74f.
These migrations have not been applied to Supabase.

Backend permissions, deployment compatibility and full-workflow
integration still require verification.

An article can belong to several topics.
Do not use news.topic_id as the membership relationship.

The earlier news_articles.news_id, categorized_at and
content_articles design is superseded as the Week 44 target.
Existing dependencies must still be checked before any retirement.

Posts, article generation and generated-output storage are deferred.

## References

- [Collected-news schema](../sql/001_create_news.sql)
- [Draft embedding migration](../sql/002_create_topic_storage.sql)
- [Local verification](topic-storage-verification.md)
- [Collector](../src/collect_news.py)
- [Uploader](../src/store_news.py)
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
| embedding | vector(384) | Proposed nullable addition; tested locally only. |

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

The draft migration uses extensions.vector(384).
NULL means no embedding is stored; it does not distinguish
unprocessed articles from failed attempts.

Before completing the implementation, agree:

- Exact input construction and missing-description handling.
- Model and input version tracking.
- Detection of changed input and outdated embeddings.
- Failure handling and regeneration rules.
- Extension version and schema in the deployment environment.

Turker owns embedding generation and grouping under #19.
Nosheen owns the agreed storage and constraints under #26.

## Topic storage

The proposed table name is public.topics.
Final table names require team confirmation.

Confirmed field requirements:

| Field | Purpose | Writer |
|---|---|---|
| id | Stable topic identifier. | Database |
| score | Calculated ranking score. | Mathias, #35 |
| score_calculated_at | Time the score was calculated. | Mathias, #35 |
| score_version | Ranking formula version. | Mathias, #35 |
| score_breakdown | Signals and their contributions. | Mathias, #35 |
| label | Generated topic headline. | Nedal, #27 |
| why_relevant_sv | Relevance explanation in Swedish. | Nedal, #27 |
| llm_relevance | AI relevance rating from 1 to 5. | Nedal, #27 |

Use llm_relevance instead of the earlier name relevance.
Whether it contributes to score remains an open decision under #35.

Field types, defaults and nullability remain draft decisions.
Confirm whether llm_relevance permits integers only or also decimals.

Also agree:

- Score scale, refresh rules and score_breakdown structure.
- Handling of failed or incomplete scoring and labelling.
- Topic identity and regrouping rules.
- Invalidation of labels and scores when memberships change.

Earlier suggestions such as velocity, swedish_signal, first_seen,
last_seen and status are not confirmed as separate stored columns.

## Article-topic linking table

The proposed name topic_articles is not yet confirmed.

| Field | Requirement |
|---|---|
| news_id | NOT NULL bigint referencing public.news(id). |
| topic_id | NOT NULL reference matching the final topics.id type. |

Require a unique pair of news_id and topic_id.
Neither field is individually unique.

For example, article 101 may link to topics 5 and 8.
The pair (101, 5) must not be stored twice.

Reject references to missing articles or topics.
The draft implementation uses ON DELETE RESTRICT for both
foreign keys. Linked articles and topics cannot be deleted.
This behavior is tested; team review and regrouping rules
remain pending.


Whether to store similarity remains open.
Its meaning, scale and update rules must be agreed if included.

Do not store rank_in_topic.

## Ranked-topic read interface

The draft read interface is implemented in
sql/004_create_topic_read_views.sql.

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

Empty topics remain visible with zero counts. The reader must
filter article_count > 0 before selecting the top topics.

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
This clarification should be recorded for team review.

Both source selection and final article ranking use description
presence, publication date descending and news_id ascending.

Sources are compared using their stored source values.
No source-name normalization is performed by these views.

Readers must explicitly order selected articles by topic_id
and rank_in_topic.

### Topic selection and counts

The Week 44 target remains up to 20 topics.
The reader controls the topic limit and explicit topic ordering.

Filter empty topics and select the ranked topics before expanding
their article rows. Do not apply the topic limit to joined
article rows.

For example, a topic containing four articles from two sources
displays two articles, one per source. Its counts remain:

- article_count = 4
- source_count = 2

Topic ranking tie-breaking, eligibility and freshness rules
still need alignment with the ranking implementation.
Similarity is not stored or used by these views.

### Permissions

Both views use security_invoker = true.
Readers need the appropriate view and underlying table permissions.
Underlying row-security rules apply to the reader.

Full-topic counts require access to all relevant linked rows.
Backend grants and permission tests remain pending.

## Article identity and duplicates

Use news.id as the shared article identifier.
Do not assume IDs from different tables refer to the same article.

IDs remain stable while records exist in this database.
They are not portable across databases or deletion and reinsertion.

The uploader trims surrounding whitespace from links, keeps the
first valid input record for each repeated link and skips links
already stored. Existing database metadata is preserved.

URL normalization, redirect resolution, tracking-parameter removal
and cross-publisher story deduplication are not implemented.

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

This collection window is not a database retention policy.
Stored articles are not automatically deleted.

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
Their treatment during embedding generation remains to be agreed.

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
PR #39 contains the draft implementation and local verification.

## Access and verification

Use backend credentials stored in environment variables or
deployment secrets. Never commit them or expose them in frontend code.

RLS is enabled on news.
Define and test the required permissions for new tables and the
read interface. Do not automatically copy legacy broad grants.

A view does not automatically provide appropriate access control.

Verification must cover:

- Preservation of original articles and IDs.
- Valid embedding dimensions and allowed missing embeddings.
- Multiple topics per article.
- Rejection of duplicate pairs and invalid references.
- Correct counts before article display limits.
- Agreed topic and article ordering.
- Repeatable writes without unintended duplicates.
- Failed processing and stale-result handling.
- Backend permissions and denied unauthorized access.
- Integration with grouping, ranking and Content readers.

Local test results do not establish production deployment.
Test against the intended deployment versions before rollout.

## Remaining decisions and checks

The two read views and the confirmed Week 44 article-selection
rule are implemented and tested in draft PR #39.

The following items remain:

- Team review of the implemented table names, field types,
  defaults and nullability.
- Confirmation of the integer-only llm_relevance contract.
- Embedding metadata, missing-description handling and
  regeneration rules.
- Topic identity and regrouping behavior.
- Review of ON DELETE RESTRICT for linked articles and topics.
- Whether similarity should be stored and used in future.
- Team review of whitespace-only descriptions being treated
  as empty.
- Topic ranking tie-breaking, eligibility and time windows.
- Source identity and normalization rules.
- Scoring and labelling freshness and failure behavior.
- Backend permissions and tests of unauthorized access.
- Supabase compatibility and preservation of existing data.
- Integration with grouping, ranking and the Content reader.
- Migration review, deployment responsibility and procedure.

Issue #26 remains open until implementation and verification
are complete. PR #39 remains Draft.
Migrations 002–004 have not been applied to Supabase.