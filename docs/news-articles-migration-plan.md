# News Articles Migration Plan

Status: Draft for review. No database changes applied.

Related: issue #26, issue #19, issue #27, issue #28, and PR #10.

The target schema depends on the finalized article data contract.
The Content view name and completion marker reflect the agreement
recorded in issue #26 and documented in PR #10.

This plan does not authorize deletion or mark the migration as completed.

## 1. Inspection results

Read-only inspection on 2026-10-22 found:

| Check | Result |
|---|---|
| Existing news_articles records | 40 |
| Unique links | 40 |
| Category is Other | 12 |
| Missing or blank category | 0 |
| Exact link matches in news | 11 |
| Unmatched links | 29 |
| Additional matches after trimming surrounding spaces | 0 |
| Titles agree for the 11 exact link matches | Yes |
| Existing news_id column | Absent |
| Existing categorized_at column | Absent |
| Existing constraints | PRIMARY KEY (id), UNIQUE (link) |

All 29 unmatched records have NULL published_at values.
Their absence from news has not yet been explained.

Existing category labels include AI, Tech, Business, Startups, and Other.
These are provisional assignments, not verified classifications under
the target contract.

The existing IDs do not identify the same article across the two tables.
For example, news_articles.id = 1 matches news.id = 1256 by link and title.

A search for news_articles in origin/main and
origin/feature/topic-grouping found documentation references only.
This does not rule out writers in n8n, other branches, or external scripts.

Nosheen reports that Turker created or populated news_articles.
The exact script or workflow, input source, and current writer status
still need confirmation with him.

These findings are a dated snapshot. Repeat the inspection before
applying any migration.

## 2. Target relationship

Subject to the finalized contract:

- news stores collected metadata and publisher RSS descriptions.
- news_articles stores classification results.
- news_articles.news_id references news.id.
- news_id must ultimately be NOT NULL and UNIQUE.
- At most one categorized record may reference each collected article.
- news_articles.categorized_at is a nullable timestamptz completion marker.
- public.content_articles is the backend Content read view.
- Existing table names and article IDs remain unchanged.

Topics owns news_articles.category and successful classification state.

The legacy news.subject column remains in place but is not the
authoritative classification field in the target database workflow.

## 3. Existing data handling

Preserve all 40 existing records during assessment.

The 11 exact link matches are candidates for a reviewed news_id backfill.
Matching identity does not validate their existing categories or justify
setting categorized_at.

The 29 unmatched records require an explicit resolution for each record.
Possible resolutions for team review are:

- Identify a verified matching collected article.
- Recover original metadata, including a verified publication date,
  and approve a separate historical import.
- Agree another preservation approach that is compatible with the
  finalized contract.

Do not infer publication dates from URL paths.
Do not invent metadata or link records using equal numeric IDs.
Do not automatically translate old category labels into new labels.
Do not delete unmatched records without explicit approval.

The NOT NULL constraint cannot be completed while unresolved records
remain in news_articles without news_id.

Preserving unresolved records with a nullable news_id is only a
transition state. It does not satisfy the final relationship requirements.

## 4. Proposed migration sequence

1. Finalize the contract in PR #10, including the allowed topic list.
2. Confirm the script or workflow that created the existing records,
   identify current writers, and coordinate their transition with #19.
3. Export a full backup of news_articles and record existing schema,
   constraints, indexes, triggers, policies, grants, and dependencies.
   Include any other data affected by the approved migration.
4. Repeat the read-only inspection, review identity matches, and record
   approved resolutions for unmatched rows.
5. Prepare versioned SQL and test it against a separate test database.
6. Add news_id as a nullable bigint during the transition, with a
   foreign key to news.id and a UNIQUE constraint.
7. Add categorized_at as a nullable timestamptz with no automatic
   completion default. Existing provisional records remain NULL.
8. Backfill only reviewed identity matches using an explicit mapping.
   Do not mark classification complete as part of identity backfilling.
9. Resolve remaining unmatched records through the reviewed plan.
10. Require news_id to be NOT NULL only after every remaining
    news_articles record has a valid reviewed reference.
11. Implement allowed-category validation for completed records,
    allowing unresolved legacy classifications to remain unmarked.
12. Implement the public.content_articles view with the seven contract
    fields and the agreed completion and category eligibility rules.
    Document and test its permissions.
13. Coordinate the #19 writer so it saves a valid category and
    categorized_at atomically after successful classification.
    Existing provisional rows require verification or reclassification.
14. Verify constraints, preservation of existing data, writer
    compatibility, and the Content read interface.
15. Record migration versions, execution results, and remaining work
    in issue #26.

A transition with nullable news_id is an intermediate state.
It does not satisfy the final acceptance criteria.

The SQL must define how completed records are restricted to the
final agreed category list. A timestamp alone is insufficient.

Use transactions for migration steps where appropriate.
Do not use cascading deletion as part of this migration.

## 5. Classification completion

The agreed target completion marker is
news_articles.categorized_at, a nullable timestamptz column.

NULL means classification completion has not been verified.

Set categorized_at together with a valid agreed category in the same
transaction, only after successful classification or explicit
verification of an existing classification.

Legacy category values, including the default Other, do not prove
successful classification. Existing provisional records remain
unmarked until verified or reclassified.

Do not populate the marker merely because a category already exists.
Do not give the column a default that marks newly inserted records
as automatically completed.

Other is a valid completed result when classification succeeds and
categorized_at is set.

Failed attempts must not set the marker or overwrite existing
successful assignments. Intentional reclassification must be explicit
and documented.

Schema implementation belongs to #26.
Categorization writer behavior belongs to #19.

This agreement is documented in PR #10. It has not yet been applied
to the database.

## 6. Content read interface

The agreed target backend view is public.content_articles.
Content readers use this name by default and keep it configurable.

The view exposes exactly seven fields:

| Field | Source |
|---|---|
| news_id | news.id |
| title | news.title |
| link | news.link |
| source | news.source |
| published | news.published |
| subject | news_articles.category |
| description | news.description |

Only records linked to an existing news article, with a valid agreed
category and non-NULL categorized_at, are eligible.

Illustrative target query, not executable against the current schema:

```sql
SELECT
    n.id AS news_id,
    n.title,
    n.link,
    n.source,
    n.published,
    na.category AS subject,
    n.description
FROM public.news AS n
JOIN public.news_articles AS na
    ON na.news_id = n.id
WHERE na.categorized_at IS NOT NULL;
```

This example assumes allowed-category validation is enforced by the
implemented schema or interface. A timestamp alone does not validate
a category label.

The implemented view must exclude unverified, failed, and incomplete
classifications. The marker is used for filtering and is not an
additional output field.

Read collected metadata and RSS description from news.
Missing RSS descriptions must not cause reading to fail.

Retain legacy duplicated metadata columns for now.
news.subject is not the authoritative topic field.
news_articles.summary must not substitute for RSS description or
Content's multi-article topic summaries.

Preserve news_id throughout Content processing and source-reference
saving. Do not match articles again by link after the reader supplies IDs.

The view, permissions, and database verification belong to #26.
Reader implementation belongs to #27.

Summary storage belongs to #28. It must save each summary and all
source references in one transaction, rolling back the whole save
if any supplied news_id does not exist in news.

Source references must use foreign keys to news.id.
Summary storage implementation and transaction tests are outside
this migration's scope.

## 7. Access

Inspect existing table permissions and Row Level Security before
implementing the interface.

Document the backend reader and writer permissions required for
both tables and public.content_articles.

A view must not unintentionally expose data or bypass intended
access rules. Select and verify its security configuration explicitly.
Do not introduce public access as part of this work.

Keep credentials in environment variables or deployment secrets.
Never commit credentials, tokens, or database passwords.

## 8. Verification

Test the migration using isolated fixtures before applying it:

- A valid news_id is accepted.
- A nonexistent news_id is rejected.
- A duplicate news_id is rejected.
- A NULL news_id is rejected in the final schema.
- Existing records are preserved according to the reviewed plan.
- Identity backfilling does not populate categorized_at.
- Existing provisional records retain NULL categorized_at.
- New records are not automatically marked completed by a default.
- Completed records cannot use an invalid or missing category.
- A successfully classified Other record is eligible.
- A provisional default Other record is excluded.
- Records without categorized_at are excluded from the Content view.
- Failed classification attempts do not mark records completed.
- Failed reclassification does not overwrite an existing successful result.
- The view returns exactly the seven contract fields.
- Joined IDs, titles, links, metadata, and descriptions refer to the
  same original article.
- An empty RSS description does not break the read interface.
- Reader and writer permissions behave as documented.
- Existing writers remain compatible after the coordinated transition.

Atomic category and completion-marker writes must be verified with
the #19 implementation.

A live read-only verification must also be recorded after migration.
Local fixture tests alone do not establish that production is migrated.

The Supabase-backed Content dry run belongs to #27.
Summary/source transaction and rollback tests belong to #28.

## 9. Recovery

Keep the full pre-migration backup and reviewed mapping available.

Document and test recovery before applying the migration.
If an error occurs within an uncommitted transaction, roll it back.

After deployment, assess new writes and downstream dependencies before
reversing schema changes. Do not blindly restore an older backup over
newer data or drop populated columns.

Coordinate recovery with any writers or readers already using the
new relationship, completion marker, or view.

## 10. Open decisions and remaining checks

- Final approval of PR #10 and the allowed topic list.
- Confirmation with Turker of the process and inputs that created
  the existing 40 records.
- Confirmation of any current external writers.
- Resolution of the 29 unmatched records.
- Verification or reclassification of provisional categories.
- The SQL mechanism for validating categories on completed records.
- Backend access requirements and view security configuration.
- Coordination of deployment with #19 and #27.

The view name public.content_articles and the categorized_at completion
marker have been agreed. Their implementation and verification remain
pending.

## 11. Completion tracking

This draft records inspection findings, agreed interface requirements,
and a proposed migration plan only.

Issue #26 remains open until the reviewed SQL migration, data handling
decisions, access instructions, and verification results are linked.

Categorization execution belongs to issue #19.
The Content reader implementation belongs to issue #27.
Generated-output storage and transactional saving belong to issue #28.

The migration plan and SQL must remain aligned with the finalized
contract in PR #10.