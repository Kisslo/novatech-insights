# Topic Storage Verification

Date: 2026-10-28
Status: Partial local verification for issue #26.
No migration has been applied to Supabase.

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