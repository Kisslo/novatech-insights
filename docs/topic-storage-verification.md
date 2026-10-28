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