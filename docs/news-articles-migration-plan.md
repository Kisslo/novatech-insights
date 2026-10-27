# News and Topics: Assessment and Migration Plan

Status: Draft updated on 2026-10-27.
No database changes have been applied through this plan.

Related:
- Issue #26: news/topics storage and ranked-topic read interface.
- PR #29: assessment and migration plan.
- Issue #19: embeddings and topic grouping.
- Issue #27: ranked-topic reading and top-20 presentation.
- PR #10: previous article data contract, requiring a linked revision.

## 1. Week 44 scope

The current goal is to support a repeatable ranked top-20 topic
workflow using collected articles.

This plan focuses on:
- Preserving collected articles in public.news.
- Defining topic storage and article-to-topic relationships.
- Supporting embedding storage needed by issue #19.
- Defining the backend read interface needed by issue #27.
- Coordinating the transition with existing readers and writers.

Posts, generated-output storage, article generation and publication
are outside this week's scope.

PR #29 remains an assessment and migration-plan PR.
Versioned SQL will be implemented in a separate PR linked to #26.

The previous proposal to link news_articles to news is superseded
as the implementation target. This does not authorize deletion of
news_articles or its records.

## 2. Existing workflow and dependencies

The collector and uploader store cleaned articles in public.news.

Earlier, Mathias reported that n8n reads public.news, categorizes
articles and writes results to public.news_articles.

A later update reports that n8n writes to RSS_feeds and groups
records by source. Source grouping is not the same as grouping
articles into related topics.

These reports must be reconciled by inspecting the actual active
workflows. Neither report alone establishes all current dependencies.

Before migration:
- Obtain links or repository exports for the active n8n workflows.
- Identify every affected reader and writer.
- Record the tables and fields each component reads or writes.
- Check how original news.id values are carried through processing.
- Identify triggers, views, functions and scheduled jobs that depend
  on affected tables.
- Record which components must change and who owns each change.

Do not stop workflows or change RSS_feeds based only on assumptions.

## 3. Historical inspection results

Read-only inspection on 2026-10-22 found:

| Check | Result |
|---|---|
| Existing news_articles records | 40 |
| Unique links | 40 |
| Category is Other | 12 |
| Missing or blank category | 0 |
| Exact link matches in news | 11 |
| Unmatched links | 29 |
| Additional matches after trimming spaces | 0 |
| Titles agree for the 11 exact matches | Yes |
| Existing news_id column | Absent |
| Existing categorized_at column | Absent |
| Existing constraints | PRIMARY KEY (id), UNIQUE (link) |

All 29 unmatched records had NULL published_at values.

Existing categories included AI, Tech, Business, Startups and Other.
These values do not prove successful classification.

The existing numeric IDs do not identify the same article across
the two tables. For example, news_articles.id = 1 matched
news.id = 1256 by link and title.

A subsequent read-only check reported:
- public.news: 1,954 records.
- public.news_articles: 40 records.
- Exact link matches: 15.
- Unmatched records: 25.

The later link counts do not establish title agreement or category
validity for all 15 matched records.

All figures above are historical observations.
Refresh counts, schema and dependency checks before migration and
record the execution date, queries and results.

## 4. Proposed article-to-topic relationship

The latest team proposal follows Kisslo's one-topic-per-article model:

- One topic can contain many articles.
- Each article can belong to at most one topic.
- news.topic_id references the topic table's primary key.
- No article/topic linking table is needed for this model.

This document uses public.topics as the proposed table name.
A teammate used the singular name topic; confirm the exact name
before implementation.

The proposed relationship is:

    public.news.topic_id -> public.topics.id

Do not make news.topic_id UNIQUE: several articles must be able to
reference the same topic.

Propose allowing news.topic_id to be NULL until grouping succeeds.
This allows collection to continue before articles are grouped.
The team must confirm this missing-value rule.

Keep original news.id values unchanged.

Before implementation, agree:
- Final table name and matching ID data types.
- Foreign-key behavior when a topic is removed.
- How articles are reassigned during regrouping.
- How topic IDs behave when topics merge or split.
- How failed or incomplete grouping is distinguished from success.

The relationship is proposed and awaits the team's final decision.
No SQL has been applied.

## 5. Proposed fields and ownership

### news

Data owns collected metadata and RSS descriptions.

Preserve existing fields and their meaning:
- id
- title
- link
- source
- published
- subject
- description
- collected_at

Kisslo's proposed additions are:
- embedding
- topic_id

The legacy subject column must not become a competing source of
topic membership. Retain it until its dependencies and future
treatment have been agreed.

Topics owns the grouping results and embedding generation.
The database migration provides the agreed storage and constraints.

Before defining embedding storage, confirm:
- Embedding model and vector dimensions.
- Input text, including title and RSS description.
- Handling of missing descriptions.
- How the model and input version are recorded.
- How missing, failed or outdated embeddings are identified.
- Regeneration rules when the input or model changes.
- Required database extension and its current installation state.

### topics

Kisslo proposed these fields:

- id
- label
- score
- source_count
- velocity
- swedish_signal
- first_seen
- last_seen
- status

These are starting points for the shared contract, not a finalized
schema. Agree types, defaults, allowed values and field meanings.

In particular, define:
- Whether source_count counts distinct publishers or feed names.
- The time window and calculation represented by velocity.
- What swedish_signal measures.
- Whether first_seen and last_seen refer to publication,
  collection or processing time.
- The score scale and when scores are refreshed.
- Whether status represents processing or editorial state.
- Any additional fields needed to identify results ready to read.

Topics owns grouping and ranking calculations.
Coordinate storage fields with their implementation.

### posts

Posts are deferred and are not created by this migration.

RSS descriptions remain publisher-provided input.
They must not be replaced by generated headlines or summaries.

## 6. Ranked-topic read interface

Agree a documented backend query or view with the owner of #27.

A ranked_topics view was suggested in the meeting.
Its exact name and definition remain to be confirmed.

The interface must allow the reader to:
- Retrieve eligible topics and their ranking information.
- Retrieve the original news records linked to each topic.
- Retain news.id for article traceability.
- Read title, link, source, published and description from news.
- Handle missing descriptions without losing article identity.
- Distinguish incomplete results from results ready to present.

Agree the output field names and types, eligibility rules,
processing freshness, ordering and tie-breaking.

The reader must request an explicit order when selecting the
top 20; it must not rely on an implicit database row order.

Keep topic selection separate from the number of linked articles:
joining articles must not cause a row limit to select fewer topics.

The database interface supports ranking results.
The ranking algorithm and top-20 presentation are separate work.

The old public.content_articles interface is not automatically
retained. Check whether any deployed reader depends on it before
deciding whether a temporary compatibility interface is needed.

## 7. Existing data preservation

Preserve existing news, news_articles and RSS_feeds data during
assessment.

Do not:
- Delete unmatched or provisional records.
- Invent publication dates or other missing metadata.
- Equate numeric IDs from different tables.
- Treat legacy category labels as verified topic assignments.
- Convert old categories into new topic groups automatically.
- Drop tables or populated columns as part of this planning PR.

The new topic workflow does not require completing the old
news_articles backfill solely to retire that design.

Before any later retirement of legacy storage:
1. Identify readers, writers and database dependencies.
2. Export affected data and capture schema and access settings.
3. Agree whether records remain, are archived or are migrated.
4. Verify that replacement workflows work.
5. Obtain and record a separate retirement decision.

## 8. Migration sequence

1. Confirm the revised scope of #26 and this plan.
2. Agree the article-to-topic relationship and exact schema with
   Topics and Content.
3. Document the revised shared data contract.
4. Inspect and link current readers, writers and n8n workflows.
5. Refresh database counts, schema and dependency checks.
6. Back up affected data, constraints, indexes, policies and grants.
7. Prepare versioned SQL in a separate PR linked to #26.
8. Test the migration and recovery in an isolated database.
9. Test the writer and reader against the agreed interface.
10. Coordinate deployment with active readers and writers.
11. Apply the reviewed migration through the agreed process.
12. Record post-migration verification and remaining work.

Prefer additive changes that preserve existing records and IDs.

Existing articles should remain ungrouped until the new grouping
process assigns a valid topic; do not manufacture topic assignments
during schema migration.

PR #29 does not apply production SQL.

## 9. Access and recovery

Inspect Row Level Security, policies and grants before creating
tables, views or functions.

Document the backend roles allowed to:
- Insert collected articles.
- Write embeddings and topic assignments.
- Write topic ranking results.
- Read ranked topics and linked articles.

A new view must not unintentionally expose data beyond the intended
access rules.

Keep credentials in environment variables or deployment secrets.

Test recovery before deployment.
Use transactions where appropriate and roll back failed,
uncommitted migration steps.

After deployment, inspect new writes and dependencies before
reversing changes. Do not restore an old backup over newer records
or drop populated columns blindly.

## 10. Verification

The implementation PR must demonstrate:

- Existing article IDs and collected metadata are preserved.
- A valid topic reference is accepted.
- A nonexistent topic reference is rejected.
- Multiple articles can reference the same topic.
- Ungrouped articles are handled according to the agreed NULL rule.
- Repeated processing does not create unintended duplicates.
- Regrouping follows the agreed reassignment rules.
- Embedding storage accepts the agreed dimensions.
- Incomplete or failed processing is not presented as ready.
- Ranked-topic ordering and tie-breaking are deterministic.
- Linked metadata and descriptions belong to the correct news IDs.
- Missing descriptions are handled clearly.
- Reader and writer permissions behave as documented.
- Existing collection remains compatible.
- The grouping, ranking and Content reader work together in a
  recorded test using the new interface.

Record isolated test results and live read-only verification after
deployment. Passing CI alone does not prove that the database has
been migrated.

## 11. Open decisions

- Confirm public.topics versus public.topic.
- Confirm one-topic-per-article and nullable news.topic_id.
- Agree topic deletion, regrouping and stable-ID rules.
- Agree final fields, types, constraints and processing-state rules.
- Confirm the embedding model, dimensions and update strategy.
- Confirm ranked-topic interface name, fields and eligibility.
- Identify and link all current readers and writers.
- Resolve the reported n8n use of news_articles and RSS_feeds.
- Assign implementation, deployment and verification owners.

## 12. Tracking and completion

- #26: database storage, relationships and backend read interface.
- PR #29: assessment and migration planning only.
- Separate implementation PR: versioned SQL and migration tests.
- #19: embeddings and topic grouping, coordinated with storage.
- #27: reading ranked topics and producing the top-20 presentation.
- #28: generated-output storage paused for Week 44.
- #30 / PR #31 and #33: further article-generation and separate
  draft-review work paused for Week 44.

Update the shared data contract and README so that the old model
is not presented as the current implementation target.

Keep #26 open until implementation, access instructions and
verification evidence are linked. Merging PR #29 alone does not
complete #26.