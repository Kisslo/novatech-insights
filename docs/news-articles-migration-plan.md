# News, Topics and Posts: Assessment and Migration Plan

Status: Draft for team review on Monday, 2026-10-26.
No database changes have been applied through this plan.

Related: PR #29 and issues #26, #19, #27, #28.
Existing data contract: PR #10.

## 1. Updated direction

On 2026-10-24, Mathias confirmed that we should adjust to
Kisslo's proposed model using news, topics and posts.

Further implementation of the earlier news_articles relationship
is paused while the replacement model is agreed.

PR #29 remains an assessment and migration-plan PR.
SQL implementation will be handled in a separate PR linked to #26,
after its scope and the revised contract are agreed.

The statement that news_articles will probably be dropped is not
approval to delete the table or its records.

## 2. Current workflow

Mathias confirmed the current flow with Turker:

1. Python collects and cleans articles.
2. Collected articles are stored in public.news.
3. n8n reads articles from public.news.
4. n8n categorizes them and writes results to public.news_articles.

The actual n8n workflow link or repository export still needs to
be supplied and recorded here.

We must inspect how the workflow carries the original news.id
and identify its current readers and writers before changing it.

The current workflow and the proposed replacement model must
remain clearly distinguished.

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
Their absence from news was not explained by this inspection.

Existing categories included AI, Tech, Business, Startups and Other.
These values do not establish verified classification completion.

The existing numeric IDs do not identify the same article across
the two tables. For example, news_articles.id = 1 matched
news.id = 1256 by link and title.

These counts are historical, not current migration inputs.
Repeat the inspection before any migration because the workflow
may have added or changed records.

## 4. Proposed model

The proposed table roles are:

| Table | Intended role |
|---|---|
| news | Collected article metadata and RSS descriptions |
| topics | Groups of related articles and topic ranking information |
| posts | Content developed from selected topics and Kisslo's input |

Kisslo's proposal includes article embeddings and a topic reference
in news, ranking information in topics, and editorial content and
publication information in posts.

These are proposed responsibilities, not a completed schema.
Exact columns, types, relationships, constraints and access rules
must be documented in the revised contract before implementation.

Keep original news.id values available throughout processing so
generated content can be traced to its source articles.

RSS descriptions must remain distinct from generated content.

## 5. Earlier design now on hold

The previous plan proposed:

- news_articles.news_id as a NOT NULL, UNIQUE foreign key.
- news_articles.categorized_at as a completion marker.
- public.content_articles as the Content read view.
- Backfilling links from news_articles to news.

These changes are not the current implementation plan following
Mathias's updated direction.

Do not implement them solely to complete the old design.
The team must decide whether any compatibility interface is still
needed during the transition.

PR #10 documented the earlier contract. The revised model and its
effect on existing interfaces must be documented and reviewed.

## 6. Existing data handling

Preserve existing news and news_articles records during assessment.

The historical 11 matches and 29 unmatched records remain useful
inspection evidence, but they do not require immediate backfilling
into a table that may be retired.

Before retiring news_articles:

- Identify its current writers, readers and dependencies.
- Repeat the record and identity checks.
- Export its data and record its schema and access configuration.
- Agree whether legacy records should be retained, archived or migrated.
- Record how any unmatched records will be handled.

Do not invent publication dates or other missing metadata.
Do not equate numeric IDs across tables.
Do not delete unmatched records without explicit approval.

Table removal requires a separate, explicit decision after data
preservation and dependent workflow changes have been verified.

## 7. Proposed implementation sequence

1. Confirm the news/topics/posts model with the team.
2. Revise the shared data contract and affected issue scopes.
3. Obtain and inspect the actual n8n workflow.
4. Refresh the read-only database assessment.
5. Agree legacy-data preservation and recovery procedures.
6. Define the new relationships and Content read interface.
7. Prepare versioned SQL in a separate implementation PR.
8. Test migrations and application changes in an isolated environment.
9. Coordinate Python, n8n and Content reader changes.
10. Apply the reviewed migration through an agreed deployment process.
11. Verify the complete flow and source traceability.
12. Consider retiring news_articles only after separate approval.

No table removal or production migration is performed by this
documentation PR.

## 8. Decisions for Monday

- What are the final columns and relationships for the three tables?
- Can an article belong to one topic or several?
- How are topic changes and regrouping handled?
- How are successfully processed articles and failed attempts identified?
- How will posts retain references to the exact source articles used?
- What interface will Content use under the new model?
- Is public.content_articles still needed for compatibility?
- Which Python functions and n8n workflow steps must change?
- How should the existing news_articles records be preserved?
- Who owns each implementation and verification task?

If embeddings are included, also agree the model, dimensions,
input text, missing-description handling, cost and regeneration rules.

## 9. Access and recovery

Inspect existing permissions, Row Level Security, policies and
dependencies before implementing new tables or views.

Document backend reader and writer access.
Keep credentials in environment variables or deployment secrets.

Back up affected data and schema before migration.
Test recovery without overwriting newer records.

Coordinate deployment and recovery with active writers and readers.

## 10. Verification requirements

The implementation PR must demonstrate that:

- Existing data is preserved according to the reviewed plan.
- Article identities remain stable.
- Relationships reject invalid references.
- Repeated processing does not create unintended duplicates.
- Failed processing does not mark work as completed.
- Topic membership and ranking follow the agreed rules.
- Content reads metadata and descriptions from the correct articles.
- Generated content retains its source references.
- Missing descriptions are handled explicitly.
- Permissions behave as documented.
- Python, n8n and Content work together in a recorded test run.

Record both isolated test results and post-migration verification.
Passing local tests does not establish that production is migrated.

## 11. Issue and PR tracking

- PR #29: assessment, historical findings and revised migration plan.
- Issue #26: database implementation scope to be revised for the new model.
- Issue #19: workflow changes to be coordinated with Turker.
- Issue #27: Content reading changes to be coordinated with Nedal.
- Issue #28: generated-output storage to be reconciled with posts.
- PR #10: existing contract to be updated or followed by a linked revision.

Link implementation PRs and verification evidence to the relevant issues.

Do not close #26 merely because this planning document is merged.