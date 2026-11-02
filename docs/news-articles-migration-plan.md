# News and Topics: Assessment and Migration Plan

Status: Draft updated on 2026-10-27.
No database changes have been applied through this plan.

Related:
- Issue #26: news/topics storage and ranked-topic read interface.
- PR #29: assessment and migration plan.
- Issue #19: embeddings and topic grouping.
- Issue #27: ranked-topic reading and presentation.
- PR #10: previous article data contract, requiring a linked revision.

## 1. Week 44 scope

The goal is to support a repeatable ranked-topic workflow using
collected articles.

This plan focuses on:
- Preserving collected articles in public.news.
- Defining topics and article-topic relationships.
- Supporting embedding storage needed by #19.
- Defining the backend read interface needed by #27.
- Coordinating changes with existing readers and writers.

Kisslo clarified that an article must be able to belong to multiple
topics, like hashtags. Use an article-topic linking table instead
of a single news.topic_id.

Posts, generated-output storage, article generation and publication
are outside this week's scope.

PR #29 remains an assessment and migration-plan PR.
Versioned SQL belongs in a separate implementation PR linked to #26.

The earlier news_articles relationship is superseded as the
implementation target. This does not authorize deletion of
news_articles or its records.

## 2. Existing workflow and dependencies

The collector and uploader store cleaned articles in public.news.

Earlier, Mathias reported that n8n reads public.news, categorizes
articles and writes results to public.news_articles.

A later update reported that n8n writes to RSS_feeds and groups
records by source. The inspected database table is named
public.rss_feeds, in lowercase.

Its columns appear consistent with feed configuration, not article
or topic storage. Its schema alone does not establish which workflow
reads or writes it.

Source grouping is not the same as grouping articles into topics.

Before migration:
- Obtain links or repository exports for active n8n workflows.
- Identify affected Python scripts, readers and writers.
- Record the tables and fields each component reads or writes.
- Check how original news.id values are preserved.
- Inspect dependent views, functions, triggers and scheduled jobs.
- Record required changes and their owners.

The actual workflow links and complete dependency inventory remain
pending. Do not stop workflows or change rss_feeds based only on
assumptions.
### Python writer inspection — 2026-10-27

Inspected src/store_news.py on origin/main at commit 6ab8736.

- Reads and validates data/news.csv.
- Inserts into public.news through the Supabase REST API only
  when run with --upload.
- Skips existing links without updating their records.
- Omits id from inserts and requests generated IDs in the response.
- Does not write to news_articles, rss_feeds or topic tables.
- The new schema must remain compatible with these inserts.

A search of origin/main/src for Supabase and database connection
patterns found matches only in this file. This does not rule out
other branches, external scripts or n8n workflows.

The actual n8n workflow has been requested from Turker.
The supplied JSON export was inspected on 2026-10-27 and has
active set to false. Its current table references are provisional;
the final dependencies must be confirmed after Turker's redesign.

### n8n workflow inspection — 2026-10-27

Workflow: [My workflow](https://novatech-solutions.app.n8n.cloud/workflow/7sGmy86NQShmTgWb)

Turker confirmed that this workflow is inactive, unfinished and
will be redesigned. Its current table references are not the
agreed future integration design.

Static inspection of the supplied JSON export found:

- active is false.
- Reads active feed configurations from rss_feeds.
- Fetches articles directly from RSS URLs.
- Assigns keyword-based subjects in JavaScript.
- Is configured to insert into news and ignore duplicate links.
- Does not read existing news articles or carry their news.id.
- Does not reference news_articles or the proposed topic tables.
- Replaces missing or invalid publication dates with the current time.
- Contains no seven-day publication-date filter.
- The Schedule Trigger has no outgoing connection in this export.

The workflow was not executed during this inspection.
This export does not establish which process created the existing
news_articles records. Final readers, writers and article-ID
handling must be confirmed after the redesign.


## 3. Inspection evidence

### Historical record checks

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

The numeric IDs do not identify the same article across the tables.
For example, news_articles.id = 1 matched news.id = 1256 by link
and title.

A subsequent read-only check reported:
- public.news: 1,954 records.
- public.news_articles: 40 records.
- Exact link matches: 15.
- Unmatched records: 25.

The later link counts do not establish title agreement or category
validity for all 15 matched records.

These counts are historical, not current migration inputs.

### Schema inspection on 2026-10-27

The supplied information_schema exports returned these public tables:
- news
- news_articles
- rss_feeds

No topic or topics table was returned in that inspection.

public.news had eight columns, all NOT NULL:

| Column | Type |
|---|---|
| id | bigint |
| title | text |
| link | text |
| source | text |
| published | timestamp with time zone |
| subject | text |
| description | text |
| collected_at | timestamp with time zone |

No embedding or topic_id column was returned for news.

public.news_articles had eight columns:

| Column | Type | Nullable |
|---|---|---|
| id | bigint | No |
| title | text | No |
| link | text | No |
| category | text | Yes |
| summary | text | Yes |
| published_at | timestamp with time zone | Yes |
| source | text | Yes |
| created_at | timestamp with time zone | Yes |

public.rss_feeds had four columns, all NOT NULL:

| Column | Type |
|---|---|
| id | bigint |
| name | text |
| url | text |
| active | boolean |

These are schema observations, not verification of active workflows,
permissions or all database dependencies.

Refresh counts, schema, constraints and dependencies before migration.
Record the execution date, queries and results in the implementation PR.

### Refreshed record counts — 2026-10-27

Read-only checks in Supabase returned:

| Check | Result |
|---|---:|
| Records in public.news | 1,954 |
| Records in public.news_articles | 40 |
| Records in public.rss_feeds | 30 |
| news_articles records with an exact link match in news | 15 |
| news_articles records without an exact link match in news | 25 |

The matched and unmatched counts total 40.
Matching links does not verify category accuracy.
No records or database structures were changed.

## 4. Article-to-topic relationship

Kisslo confirmed that an article can belong to multiple topics.
A topic can also contain multiple articles.

Use an article-topic linking table instead of news.topic_id.

This document uses public.topics and public.topic_articles as
provisional names. Confirm the final names with the team.

Proposed linking fields:

| Field | Reference |
|---|---|
| news_id | public.news.id |
| topic_id | public.topics.id |

Both fields must be NOT NULL and reference existing records.
The pair (news_id, topic_id) must be unique, for example through
a composite primary key.

Neither field is individually unique:
- One news_id may appear with several topic_id values.
- One topic_id may appear with several news_id values.

Keep original news.id values unchanged.
Store original metadata once in news rather than duplicating it
for each topic.

Articles can remain stored without topic links. The absence of links
alone does not distinguish pending, failed or completed processing.
Agree explicit processing-state rules with the grouping owner.

Agree before implementation:
- Final table names and matching ID types.
- How links are added, removed or replaced during regrouping.
- How topic IDs behave when topics merge or split.
- Foreign-key deletion behavior that protects original articles.
- Whether similarity is stored for each article-topic relationship.

The multiple-topics requirement is confirmed.
The exact schema and linking-table name remain under review.

## 5. Fields and ownership

### news

Data owns collected metadata and RSS descriptions.

Preserve existing fields:
- id
- title
- link
- source
- published
- subject
- description
- collected_at

Embedding storage is proposed for the new workflow.
Do not add news.topic_id as the article-topic relationship:
membership is represented by the linking table.

The legacy subject column is not authoritative topic membership.
Retain it until its dependencies and future treatment are agreed.

Turker owns embedding generation and topic grouping under #19.
Nosheen provides the agreed storage, constraints and documentation.
Turker confirmed on 2026-10-28:
- Embedding model: paraphrase-multilingual-MiniLM-L12-v2.
- Vector dimensions: 384.
- Input text: article title and RSS description.

The proposed linking-table name topic_articles remains unconfirmed.

Before implementing embedding storage, still agree:
- Missing-description handling.
- Model and input version tracking.
- Identification of missing, failed or outdated embeddings.
- Regeneration rules when input or model changes.
- Required database extension and its current installation state.

### topics

Confirmed field requirements — 2026-10-28:

| Field | Purpose | Owner |
|---|---|---|
| id | Stable topic identifier | Database |
| score | Calculated topic ranking score | Mathias, #35 |
| score_calculated_at | Time the score was calculated | Mathias, #35 |
| score_version | Ranking formula version | Mathias, #35 |
| score_breakdown | Signals and their contributions to the score | Mathias, #35 |
| label | Generated topic headline | Nedal, #27 |
| why_relevant_sv | Short relevance explanation in Swedish | Nedal, #27 |
| llm_relevance | AI relevance rating on a scale of 1–5 | Nedal, #27 |

Use llm_relevance consistently instead of relevance.
Whether llm_relevance contributes to the ranking formula remains
an open decision under #35.

Ranking inputs come from news through the article-topic linking table.
Keep original article metadata unchanged.

Calculate article_count and source_count when reading.
source_count counts distinct sources across all articles in the
agreed topic scope, not only the displayed articles.
Calculate rank_in_topic when retrieving selected articles.
Do not store these three calculated values separately.

Before SQL implementation, agree:
- Field types, defaults and nullability.
- Whether llm_relevance allows only integers or also decimals.
- Handling of missing or failed topic labelling and scoring.
- Score scale, refresh rules and score_breakdown structure.
- How stored labels and scores are invalidated after regrouping.

Earlier proposed fields velocity, swedish_signal, first_seen,
last_seen and status are not confirmed as separate stored columns.
Agree whether they are needed separately, derived when reading,
or represented within score_breakdown where appropriate.

Mathias owns ranking signals and the score formula.
Nedal owns generated labels, relevance explanations and AI ratings.
Nosheen provides the agreed storage, constraints and documentation.

### Article-topic linking table

The proposed minimum fields are news_id and topic_id.
Require valid references and a unique article-topic pair.

Whether to store similarity remains an open decision with Turker,
Nedal and the team. Its meaning, scale and update rules must be
defined if it is included.

Do not store rank_in_topic. Calculate it when retrieving selected
articles using the agreed selection and ordering rules.

### Deferred content

Posts and generated-output storage are outside this week's scope.

RSS descriptions remain publisher-provided input.
They must not be replaced by generated headlines or summaries.

## 6. Ranked-topic read interface

Agree a documented backend query or view with Nedal for #27.
ranked_topics is a suggested name, not a finalized interface name.

The interface must support ranked topics and original articles
connected through the article-topic linking table.

### Reader field requirements — confirmed 2026-10-28

Nedal needs to read:
- Per topic: id, score, source_count and article_count.
- Per selected article: news_id, title, source, link and description.

Nedal writes label, why_relevant_sv and llm_relevance.
llm_relevance uses a scale of 1–5 and replaces the earlier name relevance.

The example below uses topic_id to show article-topic connections.
Agree whether the final topic result exposes id or aliases it
as topic_id, and use the chosen naming consistently.

### Agreed behavior

- Expose news.id as news_id.
- Read title, link, source, published and description from news.
- Calculate article_count from the distinct articles linked to
  each topic.
- Calculate source_count from distinct sources across the topic's
  articles, not only the three displayed articles.
- Calculate rank_in_topic when retrieving selected articles;
  do not store it as a column.

Compute topic counts before applying the top-three display limit.
Document any eligibility or time-window filters consistently.

An article can appear under multiple topics. Within each topic,
it must not be duplicated or counted more than once.

### Selection and ordering

The exact top-three selection rule remains open.
Agree it with Turker and Nedal, including deterministic tie-breaking
and whether similarity influences selection.

Keep these operations distinct:
- Topic ranking determines which topics are selected.
- Article selection determines which articles appear within a topic.

Select the requested number of topics before expanding their article
rows. A joined-row limit must not accidentally reduce the number
of selected topics.

Queries must use explicit ordering rather than rely on implicit
database row order.

Support a configurable number of selected topics, such as 20 or 5.
Nedal confirmed that top five means five topics, with up to three
selected articles within each topic.

The documented Week 44 acceptance target remains top 20 unless
the team explicitly changes it. The exact rule for selecting
and ordering the three articles remains open.

### Proposed output example

The following fixture is illustrative, not production data.
Exact output names and structure still require reader review.

Assume topic 5 has five linked articles from four distinct sources.
Only three articles are selected for display.

Topic result:

| topic_id | label | article_count | source_count |
|---|---|---|---|
| 5 | AI assistants in business | 5 | 4 |

Selected article result:

| topic_id | news_id | title | source | link | description | rank_in_topic |
|---|---|---|---|---|---|---|
| 5 | 101 | Example article A | Example Source A | https://example.com/a | Example RSS description A | 1 |
| 5 | 102 | Example article B | Example Source A | https://example.com/b |  | 2 |
| 5 | 103 | Example article C | Example Source B | https://example.com/c | Example RSS description C | 3 |

The counts remain five articles and four sources even though the
displayed selection contains three articles from two sources.

The example positions illustrate the output shape only.
They do not establish the top-three selection rule.

Agree the remaining ranking fields, their types and how publication
timestamps are returned. Also document missing-value behavior,
processing eligibility and freshness.

Check for deployed dependencies before deciding whether the old
public.content_articles interface needs temporary compatibility.

## 7. Existing data preservation

Preserve news, news_articles and rss_feeds data during assessment.

Do not:
- Delete unmatched or provisional records.
- Invent publication dates or other missing metadata.
- Equate numeric IDs from different tables.
- Treat legacy category labels as verified topic assignments.
- Convert old categories into topic groups automatically.
- Drop tables or populated columns through this planning PR.

The new topic workflow does not require completing the old
news_articles backfill solely to retire that design.

Before any later retirement of legacy storage:
1. Identify readers, writers and database dependencies.
2. Export affected data and capture schema and access settings.
3. Agree whether records remain, are archived or are migrated.
4. Verify replacement workflows.
5. Record a separate retirement decision.

No legacy-table changes or production SQL are requested at this stage.

## 8. Migration sequence

1. Align #26 and this plan with the confirmed multiple-topics model.
2. Agree exact fields, table names and interfaces with Turker and Nedal.
3. Document the revised shared data contract.
4. Inspect and link active readers, writers and n8n workflows.
5. Refresh database counts, schema and dependency checks.
6. Back up affected data, constraints, indexes, policies and grants.
7. Prepare versioned SQL in a separate PR linked to #26.
8. Test migration and recovery in an isolated database.
9. Test writers and readers against the agreed interface.
10. Coordinate deployment with active components.
11. Apply the reviewed migration through the agreed process.
12. Record post-migration verification and remaining work.

Prefer additive changes that preserve existing records and IDs.

Existing articles remain without topic links until the new grouping
process creates valid relationships. Do not manufacture assignments
during schema migration.

When regrouping replaces a set of links, agree an atomic update
strategy so readers do not observe a partially replaced result.

PR #29 does not apply production SQL.

## 9. Access and recovery

Inspect Row Level Security, policies and grants before creating
tables, views or functions.

Document backend roles allowed to:
- Insert collected articles.
- Write embeddings.
- Create topics and article-topic links.
- Write ranking results.
- Read ranked topics and linked articles.

A new view must not expose data beyond the intended access rules.

Keep credentials in environment variables or deployment secrets.

Test recovery before deployment.
Use transactions where appropriate and roll back failed,
uncommitted migration steps.

After deployment, inspect new writes and dependencies before
reversing changes. Do not restore an old backup over newer records
or drop populated columns blindly.

### Access inspection — 2026-10-28

Read-only inspection found:
- RLS is enabled on news, news_articles and rss_feeds.
- No RLS policies were returned for these tables.
- anon, authenticated and service_role each have SELECT,
  INSERT, UPDATE, DELETE, REFERENCES, TRIGGER and TRUNCATE grants
  on all three tables.

These findings describe configuration, not tested effective access.
Review the broad grants, including TRUNCATE, and agree the required
backend permissions before implementing the new schema.
Do not copy these grants automatically to new tables.

No permissions or policies were changed during this assessment.

## 10. Verification

The implementation PR must demonstrate:

- Existing article IDs and metadata are preserved.
- One article can link to multiple topics.
- One topic can link to multiple articles.
- Duplicate article-topic pairs are rejected.
- Invalid article or topic references are rejected.
- NULL references in the linking table are rejected.
- Articles can remain stored without topic links.
- Repeated processing does not create duplicate links.
- Regrouping follows the agreed rules.
- Embedding storage accepts the agreed dimensions.
- Failed or incomplete processing is not presented as ready.
- Topic ordering and article selection are deterministic.
- news_id corresponds to the original news.id.
- Returned metadata and descriptions belong to that article.
- article_count counts distinct linked articles.
- source_count counts distinct sources across the topic's articles
  before limiting the displayed articles.
- An article linked to several topics is counted once within
  each topic.
- rank_in_topic is calculated during retrieval.
- Missing descriptions are handled clearly.
- Permissions behave as documented.
- Existing collection remains compatible.
- Grouping, ranking and reading work together in a recorded test.

Include a fixture with:
- An article belonging to more than one topic.
- More than three articles in a topic.
- Multiple articles from the same source.
- Additional sources outside the displayed three articles.

This verifies that relationships are many-to-many and counts are
not based only on the displayed selection.

Record isolated test results and live read-only verification after
deployment. Passing CI alone does not prove migration.

## 11. Open decisions

- Final topic and article-topic linking-table names.
- Topic identity, deletion and regrouping rules.
- Whether to store similarity and how it would be defined.
- Exact top-three selection rule and tie-breaking.
- Final field types, constraints and processing-state rules.
- Embedding update strategy, version tracking and missing-description handling.
- Ranked-topic interface name and complete output fields.
- Topic eligibility, freshness and time-window rules.
- Source identity rules for distinct-source counting.
- Confirm any change to the Week 44 top-20 acceptance target.
  The reader supports configurable topic counts, including five,
  with up to three articles per topic.
- Final readers and writers after the n8n redesign.
  The inspected n8n workflow is inactive and provisional.
- Implementation, deployment and verification owners.

Multiple topics per article is a confirmed requirement.
It is no longer an open cardinality decision.

Computing article_count, source_count and rank_in_topic when reading
is agreed. Their detailed filtering and ordering rules must be
documented consistently with the reader and ranking implementations.

## 12. Tracking and completion

- #26: storage, relationships and backend read interface.
- PR #29: assessment and migration planning only.
- Separate implementation PR: versioned SQL and migration tests.
- #19: embeddings and topic grouping, coordinated with storage.
- Mathias: ranking signals and score formula.
- #27: ranked-topic reading, headlines and presentation.
- #28: generated-output storage paused for Week 44.
- #30 / PR #31 and #33: further article-generation and separate
  draft-review work paused for Week 44.

Turker and Nedal review the interfaces used by their components.

The first checkpoint is:
- Agreed fields.
- An agreed article-topic linking table.
- An example read result reviewed by the reader and writer owners.

Update the shared data contract and README so the old model is not
presented as the current implementation target.

Keep #26 open until implementation, access instructions and
verification evidence are linked.

Merging PR #29 alone does not complete #26.