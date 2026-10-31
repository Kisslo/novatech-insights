# Topic Storage Verification

Last updated: 2026-10-31
Status: Partial verification for issue #26 and draft PR #39.
Migrations 002–004 have not been applied to Supabase.

## Current verification status

Both GitHub CI jobs passed on commit e9ba74f:

- Ruff and pytest.
- PostgreSQL migrations and topic counts.

The database CI job applies migrations 001–004 to an empty
test database and runs the count, relationship and selection tests.

The actual topic_overview and topic_top_articles views also
passed the count and selection tests locally.

Verified behavior:

- Counts include all linked articles and distinct stored sources.
- At most one article per source is displayed.
- At most three articles per topic are displayed.
- Articles with descriptions are preferred.
- Whitespace-only descriptions are treated as empty.
- Newer publication dates are preferred after description presence.
- Smaller news_id values break ties within a source.
- Empty topics appear in topic_overview with zero counts.
- Empty topics have no rows in topic_top_articles.
- Duplicate memberships and missing references are rejected.
- Linked articles and topics cannot be deleted.

Local count and selection test rows were rolled back.

Backend permissions, Supabase compatibility, existing-data
preservation and full-workflow integration still require testing.

The dated sections below describe earlier verification stages.
Their pending-work statements and example-query results are
historical; this section records the current status.

## Test environment

- Container: novatech-topic-test
- Database: novatech_test
- PostgreSQL: 17.11
- pgvector: 0.8.7
- Used an empty news table created from sql/001_create_news.sql.

Supabase inspection reported pgvector 0.8.2 as available
but not installed. These local tests do not establish
compatibility with that exact version or verify Supabase access.

## Results

| Check | Result |
|---|---|
| Draft migration executes locally | Passed |
| embedding column has type vector(384) | Passed |
| Article insertion without embedding succeeds | Passed |
| A 384-dimensional test vector is accepted | Passed |
| A 3-dimensional test vector is rejected | Passed |

Test inserts were rolled back.
Dummy vectors were used; no real embeddings were generated.

## Remaining work

- Agree embedding metadata and update rules.
- Implement and test topic storage and article-topic links.
- Implement and test the agreed read interface and permissions.
- Test against the intended deployment versions.
- Update the data contract and obtain review.
- Record deployment verification after an approved migration.

## Topic storage tests — 2026-10-29

Applied sql/003_create_topics_and_links.sql successfully in
the local novatech_test database.

| Check | Result |
|---|---|
| One article can belong to two topics | Passed |
| Duplicate article-topic pairs are rejected | Passed |
| References to missing articles are rejected | Passed |
| References to missing topics are rejected | Passed |
| llm_relevance = 6 is rejected | Passed |
| llm_relevance values 1 and 5 are accepted | Passed |
| A score without its supporting fields is rejected | Passed |
| All four score fields can be saved together | Passed |

Test records were rolled back. Failed transactions were rolled
back when their connections closed.

These are manual local tests, not production verification.
Table names, field types and the requirement to save all four
score fields together remain proposals for team review.

Read-interface behavior, backend permissions, deletion protection
and the remaining constraints still require testing.
No changes have been applied to Supabase.
## Topic count query — 2026-10-29

Ran sql/test_topic_counts.sql in the local test database.

- Created four articles: three from Source A and one from Source B.
- Displayed only the three Source A articles.
- article_count remained 4.
- source_count remained 2, including the undisplayed source.
- rank_in_topic returned positions 1, 2 and 3.
- All test records were rolled back.

This verifies the example query on a small fixture.
It does not verify a deployed read interface.
Article ID ordering is for testing only; the final article-selection
rule remains open.
### Automated assertions — 2026-10-29

Updated sql/test_topic_counts.sql to raise an exception when
expected results are incorrect.

Verified locally:
- Exactly three distinct articles are displayed.
- All displayed articles come from Source A.
- Full counts remain four articles and two sources.
- Article positions are 1, 2 and 3.

Result: PASS: all topic-count assertions passed.
Test records were rolled back.

These assertions test the example query, not a deployed read
interface. They have not been integrated into CI.

### GitHub Actions verification — 2026-10-29

The "PostgreSQL migrations and topic counts" job passed on PR #39.

It applied migrations 001, 002 and 003 to an empty temporary
PostgreSQL database and ran the topic-count assertions.

This verifies fresh-database migration execution and the example
count query. It does not verify production deployment, backend
permissions or the final ranked-topic read interface.