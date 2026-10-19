# News Data Format for Topic Grouping

Status: Proposed agreement for issue #4.
Data and Topics review is required before this agreement is final.
This document describes the CSV output implemented in PR #1 and
extended with RSS descriptions in PR #13. It also records the
Supabase storage implementation proposed in PR #21.

PR #21 has been tested against the shared Supabase project but is
awaiting review and merge. Its database structure is documented below
for review, not presented as a finalized team agreement.

Topic assignment rules and storage require confirmation by Data
and Topics. Issue #4 remains open until the acceptance criteria
have been reviewed and agreed.

## File format

- File: `data/news.csv`
- Encoding: UTF-8 with BOM. Python readers should use `utf-8-sig`.
- Delimiter: comma.
- The first row contains column names.
- Each record represents one collected article.
- Use a CSV parser because fields may contain commas or quotes.

Column order:

```csv
title,link,source,published,subject,description
```

## Field definitions

| Field | Meaning | Empty values | Assigned by |
|---|---|---|---|
| `title` | Headline supplied by the RSS feed. | Not allowed; the collector skips items without a title. | Data collector |
| `link` | Article URL supplied by the feed. Used for exact-link deduplication. | Not allowed; the collector skips items without a link. | Data collector |
| `source` | Source name from the `name` column in `data/sources.csv`. | Required by this proposed agreement. The collector does not currently validate that source names are non-empty. | Data through source configuration |
| `published` | Article publication timestamp in ISO 8601 format, in UTC. | Not allowed in current output; missing or invalid dates are skipped. | Data collector |
| `subject` | One topic label assigned to the article. | Allowed; empty means not grouped yet. | Topics: Mathias and Turker |
| `description` | Publisher-supplied RSS description, with HTML formatting removed and whitespace normalized. It is not an AI-generated summary. | Allowed; empty means no description has been saved. | Data collector |

The CSV field name is `published`. Readers should use this name,
rather than the earlier proposed name `publication_date`.

## Publication dates and collection window

Example timestamp: `2026-10-15T09:30:00Z`.

`Z` means UTC. This is the publication time, not the collection time.

The collector converts supported RSS and ISO dates to UTC.
It skips missing, invalid, timezone-free, and future dates.

The current collection window is the seven days preceding the
start of each run. The same filter applies to previously saved rows.
Articles are saved newest first.

The CSV is a rolling collection, not a permanent archive.
Topic grouping should parse timestamps as timezone-aware dates.

The uploader in PR #21 applies a seven-day filter to upload input.
It does not delete previously stored articles. Database retention
and any future cleanup policy still require team agreement.

## Subject assignment

The collector leaves `subject` empty for new articles.
It preserves existing subjects for articles retained in the CSV.

Proposed rules:

- Topics assigns one label per article.
- An empty value means "not grouped yet" and should enter grouping.
- `Other` means the article has been reviewed but does not fit
  another topic. It is not equivalent to an empty value.
- Existing non-empty values should be checked against the agreed
  topic list. Unexpected values should be flagged for review,
  not silently converted to `Other`.

The proposed topic list below is based on Nedal's issue comment
reporting Turker's first version. Topics must confirm it.

## Proposed topic list

Maintain the topic list in this section:

- AI and LLMs
- AI agents and assistants
- AI automation and workflows
- Software and APIs
- Cloud and DevOps
- Cybersecurity
- Startups and funding
- Robotics and autonomous systems
- Business and technology
- Other

Changes to the list should be reviewed by Data and Topics.
Kisslo's priority search phrases may inform future changes.

## RSS descriptions

The team has agreed to collect the RSS `description` field.
The collector removes HTML formatting and normalizes whitespace.

Descriptions come only from the RSS feed. The collector does not
fetch article pages or shorten descriptions. Their length and
completeness depend on the publisher; they are not guaranteed to
be short summaries.

Existing descriptions are preserved. Missing descriptions can be
filled when an article is still available in a feed, without changing
its subject assignment.

An empty description does not make an otherwise valid article invalid.
It means no description has been saved, for example because the feed
does not provide one or the article is no longer available in the feed.

## Example record

Illustrative example of an ungrouped article:

```csv
title,link,source,published,subject,description
Example: New open-source LLM released,https://example.com/article,Example Source,2026-10-15T09:30:00Z,,An illustrative description of the model release.
```

The empty field between `published` and `description` is `subject`.
Topics could assign `AI and LLMs` after reviewing this article.

The example date illustrates the format; it is not a permanent
test of eligibility for the rolling seven-day window.

## Interpretation by topic grouping

- Read records with a CSV parser.
- Use `title` as input for the proposed initial title-based test.
- `description` is available as additional input if Topics chooses
  to use it. Grouping must handle missing descriptions.
- Retain `link` and `source` for traceability.
- Treat exact matching links as the same collected article.
- Different URLs may still describe the same story; the collector
  does not detect that kind of duplication.
- Treat empty subjects as pending grouping.
- Flag records missing required fields rather than guessing values.

The collector saves the six documented fields.
A description is publisher-supplied text, not verified content
or an AI-generated summary.

## PostgreSQL / Supabase storage contract

### Implementation status and table

PR #21 proposes `public.news` as the storage table for collected RSS
articles. The table has been created in the shared Supabase project.
An initial upload inserted 455 articles; repeating the upload inserted
zero articles and skipped 455 existing links.

A separate table, `public.news_articles`, also exists. PR #21 does not
read or modify it. Its purpose and relationship to `public.news` need
confirmation before the team adopts a final shared contract.

The table definition is recorded in `sql/001_create_news.sql` in
PR #21. That file is not introduced by this documentation PR.

### Field mapping and database types

| CSV field | `public.news` column | PostgreSQL type | Rules |
|---|---|---|---|
| No CSV equivalent | `id` | `bigint` | Generated identity primary key; not supplied by the uploader. |
| `title` | `title` | `text` | NOT NULL; database rejects blank or whitespace-only values. |
| `link` | `link` | `text` | NOT NULL, UNIQUE; database rejects blank or whitespace-only values. |
| `source` | `source` | `text` | NOT NULL; uploader also rejects blank values. |
| `published` | `published` | `timestamptz` | NOT NULL; uploader requires a timezone-aware date within the last seven days. |
| `subject` | `subject` | `text` | NOT NULL, default empty string; proposed topic assignment field. |
| `description` | `description` | `text` | NOT NULL, default empty string; publisher-supplied RSS text. |
| No CSV equivalent | `collected_at` | `timestamptz` | NOT NULL, default `now()` at database insertion. |

The uploader strips leading and trailing whitespace from CSV values.
Empty subjects and descriptions are stored as empty strings, not NULL.
An empty description is allowed.

PostgreSQL stores `timestamptz` values as instants; their displayed
timezone depends on the client/session. Consumers should use UTC
when exchanging or displaying contract timestamps.

Despite its name, `collected_at` currently records the first database
insertion time. It does not record the original RSS retrieval time.

### Stable article identity

`news.id` is the stable identifier for a stored article within this
database. Downstream database records should reference this ID.

The same exact link is treated as the same article. Re-uploading that
link skips insertion and preserves the existing ID and fields.

CSV records do not contain database IDs. A consumer that needs to
associate a CSV article with a stored record must resolve it using
the exact stored link.

IDs are not guaranteed to remain the same after deletion and
reinsertion or when loading articles into a different database.
They are not guaranteed to be consecutive.

URL normalization, redirects, tracking-parameter removal, and
recognition of the same story at different URLs are not implemented.
A changed URL may therefore create another article record.

### Duplicate and update behavior

The database enforces a UNIQUE constraint on `link`.

The uploader in PR #21:
- Deduplicates upload input by exact link after trimming whitespace.
- Keeps the first valid CSV record when input links repeat.
- Inserts batches of up to 100 articles.
- Uses `on_conflict=link` with `resolution=ignore-duplicates`.
- Leaves all existing database fields unchanged for duplicate links.

Consequently, a later CSV description or subject does not update an
existing database article. The collector's CSV description enrichment
and the uploader's database behavior are different.

Each batch is a separate request. If a later batch fails, earlier
batches may already be stored. Rerunning skips existing links.

### Topic assignment storage — proposed, not yet agreed

The proposed initial storage location is `public.news.subject`,
with one topic label per article:
- Empty string means pending grouping.
- `Other` means reviewed but outside the other agreed labels.
- Topics owns assignment and validation against the agreed label list.
- Data ingestion must preserve existing assignments.

The current uploader can insert a subject supplied in a CSV record,
but it does not update an existing article's subject. A grouping
write-back operation is not implemented in PR #21.

Topics should confirm whether it will write assignments to
`news.subject` using `news.id` as the record identifier. If multiple
topics, assignment history, confidence scores, or model versions are
needed, a separate assignment structure must be agreed before
implementation.

This proposal does not define an implemented write-back API or grant
database access to a grouping component.

### Access and retention

Row Level Security is enabled on `public.news`.
The uploader uses a backend secret API key, which bypasses RLS.
Real credentials belong in local `.env` or the deployment's secret
configuration, never in Git or frontend code.

The current implementation does not add client-facing RLS policies.

The seven-day input window does not impose database retention.
Stored articles remain until a separate cleanup process is agreed
and implemented. No such process is included in PR #21.

## Remaining decisions and follow-up work

- Confirm `public.news` as the shared ingestion table and clarify
  the purpose of the existing `public.news_articles` table.
- Confirm topic assignment storage and the grouping write-back interface.
- Confirm the initial topic list and handling of unexpected labels.
- Agree database retention and cleanup requirements.
- Decide whether database description enrichment is required.
- Validate non-empty source names in the collector; the uploader
  already performs this check.
- Review existing manual subject labels against the agreed list.
- Avoid concurrent writes to `data/news.csv`.

UTC conversion is already implemented in PR #1.
RSS description collection is already implemented in PR #13.

## Review checklist

- [ ] Data has reviewed field definitions and current behavior.
- [ ] Data and Topics have agreed the shared table and field mapping.
- [ ] Data and Topics have reviewed database types and empty values.
- [ ] Data and Topics have agreed article identity and duplicate behavior.
- [ ] Topics has confirmed topic storage, ownership, and write-back needs.
- [ ] Topics has confirmed the initial topic list.
- [ ] Data and Topics have reviewed description handling.
- [ ] Retention behavior and unresolved implementation work are recorded.
- [ ] Issue #4 acceptance criteria have been reviewed and agreed.

Keep issue #4 open until Data and Topics have reviewed and agreed
the acceptance criteria. Documenting a proposal does not itself
establish team agreement.