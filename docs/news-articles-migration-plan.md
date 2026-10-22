# News Articles Migration Plan

Status: Draft for review. No database changes applied.

Related: issue #26, issue #19, issue #27, and PR #10.

The target schema depends on the finalized article data contract.
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
| Existing constraints | PRIMARY KEY (id), UNIQUE (link) |

All 29 unmatched records have NULL published_at values.
Their absence from news has not yet been explained.

Existing category labels include AI, Tech, Business, Startups, and Other.
These are provisional assignments, not verified classifications under
the proposed contract.

The existing IDs do not identify the same article across the two tables.
For example, news_articles.id = 1 matches news.id = 1256 by link and title.

A search for news_articles in origin/main and
origin/feature/topic-grouping found documentation references only.
This does not rule out writers in n8n, other branches, or external scripts.
The process that created the existing records remains to be confirmed.

## 2. Target relationship

Subject to the finalized contract:

- news stores collected metadata and publisher RSS descriptions.
- news_articles stores classification results.
- news_articles.news_id references news.id.
- news_id must ultimately be NOT NULL and UNIQUE.
- At most one categorized record may reference each collected article.
- Existing table names and article IDs remain unchanged.

Topics owns news_articles.category.
The legacy news.subject column remains in place but is not the
authoritative classification field in the target database workflow.

## 3. Existing data handling

Preserve all 40 existing records during assessment.

The 11 exact link matches are candidates for a reviewed news_id backfill.
Matching identity does not validate their existing categories.

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

## 4. Proposed migration sequence

1. Finalize the contract in PR #10.
2. Identify current writers and coordinate their transition with issue #19.
3. Export a full backup of news_articles and record existing schema,
   constraints, indexes, triggers, policies, grants, and dependencies.
4. Review identity matches and record resolutions for unmatched rows.
5. Prepare versioned SQL and test it against a separate test database.
6. Add news_id as a nullable bigint during the transition, with a
   foreign key to news.id and a UNIQUE constraint.
7. Backfill only reviewed identity matches using an explicit mapping.
8. Resolve all remaining unmatched records through the reviewed plan.
9. Require NOT NULL after verifying that every record has a valid news_id.
10. Verify constraints, writer compatibility, and the Content read interface.
11. Record the migration version, execution results, and remaining work
    in issue #26.

A transition with nullable news_id is an intermediate state.
It does not satisfy the final acceptance criteria.

Use transactions for migration steps where appropriate.
Do not use cascading deletion as part of this migration.

## 5. Classification completion

Legacy category values, including the default Other, do not prove that
categorization completed successfully.

Agree and document a completion rule with issue #19 before exposing
records to Content. Existing provisional records require verification
or reclassification before they become eligible.

Failed or incomplete categorization must not be exposed as completed.
Other is a valid result only after successful classification.

## 6. Content read interface

The interface must expose:

| Field | Source |
|---|---|
| news_id | news.id |
| title | news.title |
| link | news.link |
| source | news.source |
| published | news.published |
| subject | news_articles.category |
| description | news.description |

The relationship is:

```sql
news_articles.news_id = news.id
```

The following query illustrates the field mapping only.
It is not executable against the current schema and is not a complete
Content interface until the agreed completion rule is enforced:

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
    ON na.news_id = n.id;
```

The final backend query or view must exclude unverified, failed,
and incomplete classification results.

Read collected metadata and RSS description from news.
Retain legacy duplicated metadata columns for now.
news_articles.summary must not substitute for RSS description or
Content's multi-article topic summaries.

## 7. Access

Inspect existing table permissions and Row Level Security before
implementing the interface.

Document the backend reader and writer permissions required.
A view must not unintentionally expose data or bypass intended access rules.
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
- Joined IDs, titles, links, metadata, and descriptions refer to the
  same original article.
- A successfully classified Other record is eligible.
- A provisional default Other record is excluded.
- Failed and incomplete classifications are excluded.
- Existing writers remain compatible after the coordinated transition.

A live read-only verification must also be recorded after migration.
Local fixture tests alone do not establish that production is migrated.

## 9. Recovery

Keep the full pre-migration backup and reviewed mapping available.

Document and test recovery before applying the migration.
If an error occurs within an uncommitted transaction, roll it back.

After deployment, assess new writes and downstream dependencies before
reversing schema changes. Do not blindly restore an older backup over
newer data or drop populated columns.

## 10. Open decisions

- Final approval of PR #10 and the allowed topic list.
- Which process created the existing 40 records.
- Whether any external writer currently uses news_articles.
- Resolution of the 29 unmatched records.
- Verification or reclassification of provisional categories.
- The classification completion rule shared by issues #19, #26, and #27.
- Backend access requirements for the Content interface.

## 11. Completion tracking

This draft records inspection findings and a proposed plan only.

Issue #26 remains open until the reviewed SQL migration, data handling
decisions, access instructions, and verification results are linked.

Categorization execution belongs to issue #19.
The Content reader implementation belongs to issue #27.