# Topic Storage Verification

Last updated: 2026-11-03
Status: Local and CI verification for issue #26 and draft PR #39.
Migrations 002–006 have not been applied to Supabase.

## Current verification status

All three GitHub CI checks passed on commit 0eb4cee:

- Ruff and pytest.
- PostgreSQL tests (0.8.2-pg17).
- PostgreSQL tests (pg17).

CI tests migrations 001–005 in an empty PostgreSQL database
and a separate database with simulated Supabase default grants.
It checks that automatic grants are removed before applying
migration 006, then verifies actual backend permissions in
both databases.

These checks do not establish deployment or full-workflow
integration in Supabase.

## Verified storage and read behavior

- Topic counts include all linked articles and distinct stored sources.
- Article selection returns at most three articles per topic,
  with at most one article per source.
- Articles with descriptions are preferred; whitespace-only
  descriptions are treated as empty.
- Publication date descending and news_id ascending determine
  the remaining article order.
- Empty topics remain visible in topic_overview with zero counts.
- Empty topics have no rows in topic_top_articles.
- Duplicate memberships and missing references are rejected.
- Foreign keys prevent deletion of linked articles and topics.
- Reader permissions and row-security policies affect view results.

## Group saving

Migration 005 defines public.save_topic_group(bigint[]).

Verified locally and in CI:

- A topic and all its article links are saved together.
- Saving the same article-ID set reuses the existing topic.
- Reordering or repeating input IDs does not create another topic.
- Reusing a topic preserves its existing label and score fields.
- A missing article reference causes the save to fail without
  leaving a partial topic or membership records.

Calls use a transaction-level advisory lock. Membership writers
must use this function for the locking convention to work.
Concurrent saves have not been tested with parallel sessions.

A changed article-ID set creates a new topic. Existing topics
are not retired, replaced or deleted automatically. The team
must agree how older and overlapping groups should be handled.

## Python integration

src/group_news.py remains read-only unless --save is supplied.
With --save, it sends each full group to the database function
through the Supabase REST API.

The display limits do not limit the groups or memberships saved.
Each group is saved in a separate request. If a later group
fails, earlier groups may already be committed.

Python tests use fake responses and verify:

- The request includes all distinct article IDs.
- The secret key is sent only in the apikey header.
- Invalid article IDs are rejected before sending a request.
- HTTP errors, connection failures and invalid responses are handled.
- Saving requires the explicit --save option.
- A saving failure stops processing subsequent groups.

These tests do not verify a live REST API connection.

## Backend permissions

Migration 006 defines permissions for the shared service_role:

- SELECT on news, topics, topic_articles and both read views.
- INSERT on topics and topic_articles.
- USAGE on topics_id_seq.
- EXECUTE on save_topic_group(bigint[]).
- UPDATE on score, score_calculated_at, score_version and
  score_breakdown in topics.

The migration preserves existing news permissions and adds
SELECT access. It does not restrict other existing news grants.

The backend test uses the actual migration grants with a
non-superuser service_role that bypasses RLS.

Verified locally and in CI:

- The backend reads news and saves or reuses complete groups.
- It updates the four ranking fields.
- It reads both views and their full topic counts.
- Updating existing labels is denied.
- Updating memberships is denied.
- Deleting topics or memberships is denied.

All programs using service_role share these permissions.
They are not isolated from one another. Direct INSERT access
is available because the saving function uses SECURITY INVOKER;
using the function is an application convention.

Migration 006 skips its grants if service_role does not exist.
CI creates that role before applying and testing the grants.

Test records are rolled back. Grants applied by migration 006
remain in the local test databases.

## Remaining review and deployment work

- Review the schema, saving behavior and shared backend permissions.
- Agree how changed, overlapping and old groups are handled.
- Confirm embedding metadata, update and regeneration requirements.
- Align topic eligibility, freshness and source identity rules.
- Update the data contract and usage documentation.
- Confirm deployment responsibility and migration order.
- Verify compatibility and existing-data preservation in the
  intended Supabase environment.
- Test actual REST API access and the complete
  grouping-to-ranking-to-reader workflow.

PR #39 remains Draft. Passing CI does not mean issue #26 is
fully complete or that the database changes are deployed.

## Historical verification notes

The sections below record earlier stages. Their statements
about pending implementation and tests describe those dates,
not the current status above.

## Permission verification - 2026-10-31

sql/test_topic_permissions.sql passed locally and in GitHub CI.
Both CI jobs passed on commit 476780f.

Verified with test roles:

- A role without view permissions cannot read either view.
- View grants alone do not provide underlying table access.
- A reader with SELECT grants but no matching RLS policies
  sees no rows.
- Both views respect the reader's row-security policies.
- Counts include only articles visible to the reader.

Test roles, policies, grants and rows were rolled back.

These checks verify the views with local test permissions.
Final backend grants, Supabase roles and production access
still require agreement and verification.

## Supabase default-permission tests - 2026-10-31

Both CI jobs passed on commit 8c8c617.

A separate local/CI database reproduces the inspected Supabase
default grants for anon, authenticated and service_role.

Verified:

- Migrations 001–004 execute successfully with these defaults.
- Automatic grants are removed from topics, topic_articles,
  topic_overview, topic_top_articles and topics_id_seq.
- Existing news grants remain unchanged.
- Count, relationship, selection and row-security tests pass
  in this environment.

 Final backend grants are still pending. In the test database,
service_role has no access to the new topic objects.
Explicit backend grants still need to be defined.

This is a simulation of the inspected permissions, not full
Supabase compatibility verification. pgvector 0.8.2 compatibility
and production integration remain unverified.

No migrations were applied to Supabase during these checks.

## pgvector 0.8.2 verification - 2026-11-01

Migrations 001–004 and all five SQL test scripts passed locally
using pgvector/pgvector:0.8.2-pg17 with simulated Supabase
default grants.

Verified versions:
- PostgreSQL 17.10
- pgvector 0.8.2

Passing tests cover default permissions, topic counts,
relationships, article selection and reader row security.

This verifies the tested behavior with pgvector 0.8.2.
The inspected Supabase server uses PostgreSQL 17.11, so this
is not an exact match of the full Supabase environment.

No migrations were applied to Supabase. Final backend grants
and full-workflow integration remain pending.

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
