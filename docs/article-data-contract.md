# Article Data Contract

Status: Proposed agreement for issue #4.
Data and Topics must review the pending decisions before this contract
is final. Keep issue #4 open until its acceptance criteria are agreed.

## Scope and references

This contract defines how Data, Topics, and Text identify and exchange
collected news articles.

Supabase storage was implemented in merged PR #21.

Implementation details are maintained in:

- [README](../README.md): collection, CSV format, configuration, and upload commands.
- [News table definition](../sql/001_create_news.sql): database columns and constraints.
- [Collector](../src/collect_news.py): RSS collection behavior.
- [Uploader](../src/store_news.py): validation and database insertion.

This document records interface rules and pending agreements.
It does not introduce database or application changes.

## Article fields and database mapping

The current ingestion table is `public.news`.
The six CSV fields map directly to columns with the same names.

| CSV field | Database column | PostgreSQL type | Meaning and empty-value rule |
|---|---|---|---|
| None | `id` | `bigint` | Generated identity primary key. Shared reference for stored articles. |
| `title` | `title` | `text` | Publisher headline. Required and non-blank. |
| `link` | `link` | `text` | Article URL. Required, non-blank, and unique. |
| `source` | `source` | `text` | Source name. Required and non-blank at ingestion; SQL enforces NOT NULL. |
| `published` | `published` | `timestamptz` | Publication time. Required and timezone-aware. |
| `subject` | `subject` | `text` | Proposed topic assignment field. Empty string means pending grouping. |
| `description` | `description` | `text` | Publisher-supplied RSS description. Empty string is allowed. |
| None | `collected_at` | `timestamptz` | First database insertion time, default `now()`. |

All database columns are NOT NULL.
`subject` and `description` default to empty strings.

Use `published` as the shared publication-date field name.
Do not substitute `publication_date` or `published_at` without an
explicit mapping.

Exchange timestamps in UTC, for example `2026-10-21T09:30:00Z`.
Database clients may display `timestamptz` values in another timezone.

Despite its name, `collected_at` records database insertion time,
not the original RSS retrieval time.

A separate `public.news_articles` table exists. Its purpose and
relationship to `public.news` remain to be clarified. This contract
does not define a mapping between those tables.

## Article identity and duplicate handling

Use `news.id` when referencing stored articles from grouping,
summaries, or other database records.

- The same exact stored link identifies the same collected article.
- Ingestion trims surrounding whitespace before comparing links.
- The database enforces uniqueness on `news.link`.
- Repeated uploads preserve the existing article ID and fields.
- CSV records have no database ID; resolve them using the stored link.
- IDs are stable within this database while the record exists.
  They are not portable across databases or deletion and reinsertion.

URL normalization, redirect resolution, tracking-parameter removal,
and detection of the same story at different URLs are not implemented.
Different URLs may therefore represent the same story.

The current uploader skips existing links. It does not update an
existing article's subject or description from a later CSV record.

## Field ownership and descriptions

Data owns collected article metadata and RSS descriptions.
Topics owns topic assignment.
Text owns generated summaries and drafts.

An RSS description is publisher-supplied text, not an AI-generated
summary or verified article content.

Missing descriptions are allowed. Downstream components must handle
them without treating an otherwise valid article as invalid.

Generated summaries and drafts must remain distinguishable from
publisher descriptions.

## Proposed topic assignment agreement

The proposed initial storage location is `public.news.subject`,
with one topic label per article.

- Empty string means not grouped yet.
- `Other` means classified but outside the other agreed labels.
  It does not imply human review or approval.
- Topics validates assignments against the agreed topic list.
- Unexpected labels should be flagged rather than silently changed.
- Data ingestion must preserve existing topic assignments.

The collector preserves subjects for retained CSV records.
The uploader preserves existing database records.

PR #11 currently produces separate CSV output. That output does not
automatically update `news.subject`.

Data and Topics must agree how grouping results are written back,
using `news.id` to identify stored articles. A database write-back
operation is not supplied by the ingestion uploader.

If multiple topics, assignment history, confidence scores, or model
versions are needed, agree their storage before implementing them.

### Initial topic list — pending Topics confirmation

The earlier proposed list is:

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

This list is not yet final. Topics must reconcile it with the labels
used by the current grouping implementation before agreement.
Changes should be reviewed by Data and Topics.

## Proposed Text output storage

Nedal has proposed separate tables for summaries, source references,
drafts, and draft versions.

See the [Text storage proposal in PR #10](https://github.com/Kisslo/novatech-insights/pull/10#issuecomment-6312435947).

The proposal references collected articles through `news.id`.
It is pending team review; this document does not establish that
the proposed tables or workflow constraints are implemented.

Text should confirm its output requirements. Data, Topics, and Text
must agree the relationships before the shared schema is extended.

## Collection window and retention

The CSV is a rolling seven-day collection.
The uploader also validates publication dates against a seven-day
input window.

This input window is not a database retention policy.
Previously stored articles are not automatically deleted.

Any cleanup policy must consider downstream references to `news.id`
and be agreed before implementation.

## Access

Backend credentials belong in local `.env` files or deployment secret
configuration. Never commit them or expose them in frontend code.

Row Level Security is enabled on `public.news`.
The current uploader uses a backend secret key and does not introduce
client-facing access policies.

Access for grouping, Text, or a dashboard requires an appropriate
backend integration or separately agreed access policies.

## Pending decisions

- Confirm the shared table and clarify the role of `news_articles`.
- Agree the topic list and grouping write-back interface.
- Review the proposed Text output schema and article references.
- Agree retention and cleanup requirements.
- Decide whether existing database descriptions need enrichment.
- Record any required implementation changes as follow-up work.

## Review checklist

- [ ] Data has reviewed field meanings, types, and empty values.
- [ ] Data and Topics have agreed article identity and duplicate rules.
- [ ] Data and Topics have confirmed the shared table and mapping.
- [ ] Topics has confirmed the topic list and assignment storage.
- [ ] Data and Topics have agreed the grouping write-back interface.
- [ ] Data and Topics have reviewed description handling.
- [ ] Retention behavior and remaining work are recorded.
- [ ] Issue #4 acceptance criteria have been reviewed and agreed.

Review of this documentation does not by itself implement the
pending interfaces or approve the separate Text storage proposal.