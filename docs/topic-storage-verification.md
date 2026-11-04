# Topic Storage Verification

Last updated: 2026-11-04

Issue: #26

PR: #39

Migrations 002–006 have NOT been applied to Supabase.
No production backfill or live REST verification has been performed.

## Current local results

The following results were confirmed locally on 2026-11-04.

| Check | Result |
|---|---|
| Full Python test suite | 241 passed |
| Repository-wide Ruff check | Passed |
| Repository-wide Ruff formatting check | Passed; 43 files already formatted |
| Grouping Python tests | 21 passed |
| Storage source-normalization tests | 5 passed |
| Source-normalization backfill tests | 5 passed |
| SQL article selection | Passed |
| SQL Unicode source counts and selection | Passed |
| SQL full-topic counts and empty topics | Passed |
| SQL reader permissions and row security | Passed |
| SQL backend permissions, including label writeback | Passed |

The three focused Python test files were initially run separately.
The complete repository test suite subsequently passed with 241 tests.

SQL fixture records were rolled back. The row-security test also rolled
back its temporary roles, policies and grants.

Migration changes applied to the local test database remain there.

## Current CI status

All three CI checks passed on the latest confirmed pushed commit,
a8f979f:

- Ruff and pytest.
- PostgreSQL tests (0.8.2-pg17).
- PostgreSQL tests (pg17).

That result predates the current source-key, SECURITY DEFINER,
label-permission and backfill changes.

The current changes still need to be committed, pushed and checked
by CI. Historical green checks do not validate the newer changes.

## Local environment and migration handling

Container: novatech-topic-test

Database: novatech_test

The existing local database already had the embedding column.

Instead of rerunning migration 002, the new source_normalized column
was added separately with type text and COLLATE "C".

Updated migrations 004, 005 and 006 were applied locally.

Migration 006 was reapplied after migration 004 because migration 004
revokes the view grants.

These local steps do not establish that the revised migrations execute
successfully from scratch. CI provides the fresh-database checks.

Do not rerun migration 001 against the existing production news table.

## Source normalization

The shared Python rule is:

    (source or "").strip().casefold()

The uploader stores this result in news.source_normalized.
Grouping uses the same shared helper.

The original source name remains available for display. Existing
uploader trimming of surrounding whitespace is unchanged.

SQL views compare stored keys directly instead of using lower() and
ASCII-only trimming.

Python tests cover:

- Reuters and reuters.
- Straße and STRASSE.
- Surrounding nonbreaking spaces.
- Tabs, newlines and ordinary spaces.
- Swedish letter case.
- Missing and blank source names.

The SQL Unicode fixture verifies:

- Four articles with Reuters/reuters and Straße/STRASSE.
- A source_count of two.
- One selected article per normalized source.
- Smaller article IDs resolve equal description/date ties.

The existing eight-article selection fixture still passes:

- Full article count: eight.
- Full normalized source count: five.
- Selected order: Source B, Source C, Source A.
- Description presence takes priority over recency.
- Whitespace-only descriptions are treated as empty.
- Smaller news_id resolves the Source C tie.

## Existing-row backfill

src/backfill_source_normalization.py is implemented.

Its tests use fake responses and verify:

- Default operation performs reads only.
- Pagination continues across short pages until an empty page.
- Updates change only source_normalized.
- Updates check the article ID, original source and previous key.
- Already-correct keys are skipped.
- An update matching no visible row stops the run.
- Filter quoting handles quotes and backslashes.
- Missing required fields stop processing before writing that row.

The backfill has NOT been run against Supabase.

The tests do not establish live PostgREST filter behavior, complete
row visibility or UPDATE permission.

Before production use, verify the required access and coordinate
article writers. All required existing rows must have correct keys,
and future writers must maintain those keys.

## Topic counts and selected articles

The updated count test passed locally.

Its fixture contains four articles from two normalized sources.

Verified:

- article_count remains four.
- source_count remains two.
- Two articles are displayed, one per source.
- The newest Source B article precedes the newest Source A article.
- Display ranks are one and two.
- Empty topics appear in topic_overview with zero counts.
- Empty topics have no selected articles.

Counts include all linked articles before display selection.

The views have no publication-date or lifecycle filter.

NULL and empty normalized keys do not contribute to source_count.
They share one article-selection bucket.

## Reader permissions and row security

The updated sql/test_topic_permissions.sql passed locally.

Verified:

- A role without view grants cannot read either view.
- View grants alone do not provide underlying table access.
- A reader with SELECT grants but no matching RLS policies sees no rows.
- Both views respect the reader's row-security policies.
- Counts include only reader-visible articles.
- Hidden articles and hidden topic memberships are not exposed.

The views remain SECURITY INVOKER.

## Group saving and backend permissions

save_topic_group(bigint[]) now uses SECURITY DEFINER with
search_path = pg_catalog.

The function and both topic tables were confirmed to be owned by
postgres in the local database.

Deployment must verify the trusted function owner, its required
privileges and restricted EXECUTE grants.

The updated backend test passed using the actual migration 006 grants
and a non-superuser service_role with BYPASSRLS.

Verified:

- Effective direct INSERT privileges on topic tables are absent.
- Direct topic and membership inserts are denied.
- Saving through the function succeeds.
- Reordered article IDs reuse the existing complete group.
- The four ranking fields can be updated.
- Both views and full counts are readable.
- label, why_relevant_sv and llm_relevance can be updated.
- Label writeback does not alter ranking fields.
- Blank labels and explanations are rejected.
- Out-of-range relevance is rejected.
- Group reuse preserves labels and ranking fields.
- Membership updates are denied.
- Topic and membership deletes are denied.

All programs using service_role share these permissions.

The function uses a transaction-level advisory lock.
Parallel-session concurrency has not been tested.

The existing save-group test also checks exact-set reuse, metadata
preservation and rollback when an article reference is missing.
It needs no source-key fixture change because it does not read the
source-count or selection views. Its latest version remains covered
by the pending CI run.

## Automatic Supabase-style grants

CI creates a separate novatech_permissions_test database with simulated
Supabase default grants.

It applies migrations 001–005 and tests automatic-grant removal BEFORE
applying migration 006.

The default-permission test was extended to check that anon,
authenticated and service_role cannot execute save_topic_group before
the explicit backend grant.

This new assertion has not yet been run for the current changes.
It will run in the existing CI workflow.

Do not run this pre-006 test against a database where migration 006
has already granted service_role access.

setup_supabase_permission_test.sql is LOCAL/CI ONLY.
Never run it in the real Supabase project.

## CI coverage

The workflow tests two pgvector image tags:

- 0.8.2-pg17.
- pg17.

For each image, it:

1. Applies migrations 001–005 to an empty database.
2. Runs counts, constraints, selection, reader-permission and saving tests.
3. Creates a separate database with simulated Supabase default grants.
4. Applies migrations 001–005 there.
5. Checks automatic grants before migration 006.
6. Runs the SQL assertions in that database.
7. Applies migration 006 and tests backend permissions in both databases.

The Python job runs repository-wide Ruff, formatting checks and pytest.

No workflow change was needed for the current additions.

## Lifecycle and application integration

Changed article-ID sets can create new topics. Existing topics are not
automatically retired, updated or deleted.

Old-topic handling was accepted as a follow-up.

A later review proposed last_seen_at and Telegram-related status values.
Neither is implemented. Their scope and behavior still need agreement.

A non-NULL label does not establish that a topic is current.

This PR grants label writeback permissions. The application code that
generates and saves labels is planned separately.

Grouping saves each complete group in a separate REST request.
Ranking updates are proposed per topic, with all four ranking fields
sent together. There is no ranking batch RPC.

## Remaining verification

Before merging:

- Inspect the final changes and finish documentation/comment updates.
- Settle the scope of the later lifecycle/status suggestions.
- Commit and push the changes.
- Confirm all CI checks pass for the final commit.

Before production use:

- Verify the migration plan against the existing Supabase schema.
- Confirm ownership, extension compatibility and permissions.
- Preserve news, news_articles, rss_feeds and existing IDs.
- Verify source-key backfill access and complete its execution.
- Verify live REST reads, group saves, label/ranking updates and views.
- Test the complete grouping-to-ranking-to-reader workflow.

Local SQL and mocked API tests do not establish production readiness.
Merging PR #39 does not automatically complete issue #26.

## Historical evidence

These results describe earlier versions, not the current unpushed code.

| Date / commit | Historical result |
|---|---|
| 2026-10-29 | Local topic constraints and early count-query assertions passed. |
| 2026-10-29 | GitHub Actions verified the early migrations and count query. |
| 476780f | Reader-permission and RLS tests passed in CI. |
| 8c8c617 | Simulated Supabase default-grant tests passed in CI. |
| 2026-11-01 | Local pgvector 0.8.2 migration and SQL tests passed. |
| 0eb4cee | Earlier full CI checks passed. |
| 7f1ff0f | CI passed after the earlier source-comparison formatting fix. |
| a8f979f | Latest confirmed pushed commit; all three CI checks passed. |

Earlier tests used different source comparison rules and backend grants.
Those earlier permissions and query examples are superseded by the
current implementation described above.

No migrations were applied to Supabase during these checks.