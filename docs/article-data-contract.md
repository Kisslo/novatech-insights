# Article Data Contract

Status: Proposed for final review under issue #4 / PR #10.

This document defines the target agreement between Data, Topics,
and Content. Current behavior and pending implementation are
identified separately. This documentation does not migrate data
or rename tables.

## References

- [README](../README.md): setup and execution instructions.
- [Collected-news SQL](../sql/001_create_news.sql): current news schema.
- [Collector](../src/collect_news.py): RSS collection.
- [Uploader](../src/store_news.py): CSV validation and insertion.
- [Issue #26](https://github.com/Kisslo/novatech-insights/issues/26):
  table relationship, migration, read interface, and verification.
- [Issue #19](https://github.com/Kisslo/novatech-insights/issues/19):
  Python categorization through n8n.
- [Issue #27](https://github.com/Kisslo/novatech-insights/issues/27):
  Content reading categorized Supabase articles.

## Table roles and implementation status

| Table | Role | Owner |
|---|---|---|
| public.news | Collected article metadata and RSS description. | Data |
| public.news_articles | Categorized articles and assigned category. | Topics |

Both tables exist. The supplied current table definitions contain
no declared relationship between them.

The target relationship, migration, and Content read interface
described below are pending implementation and verification in #26.
Categorization integration is tracked in #19; Content consumption
is tracked in #27.

Do not assume existing records already satisfy this target contract.

## Collected article fields

The collector produces these CSV columns:

title,link,source,published,subject,description

| CSV field | news column | PostgreSQL type | Rule |
|---|---|---|---|
| None | id | bigint | Generated identity primary key. Shared collected-article ID. |
| title | title | text | Required and non-blank. |
| link | link | text | Required, non-blank, and UNIQUE. |
| source | source | text | Required and non-blank at upload; SQL enforces NOT NULL. |
| published | published | timestamptz | Required publication instant. |
| subject | subject | text | Legacy field retained for compatibility; not authoritative classification in the target database workflow. |
| description | description | text | Cleaned publisher RSS description; empty string allowed. |
| None | collected_at | timestamptz | First database insertion time, default now(). |

All current news columns are NOT NULL.
subject and description default to empty strings.

collected_at records database insertion time, not the original
RSS retrieval time.

## Shared identity and target relationship

The target news_articles.news_id column is:

- bigint
- NOT NULL
- UNIQUE
- A foreign key referencing public.news(id)

This permits zero or one categorized record per collected article.
Every categorized record must reference an existing collected article.
Invalid references and duplicate news_id values must be rejected.

news_articles.id remains that table's own primary key.
It must not be assumed to equal news.id.

Use news.id, exposed as news_id, for shared article traceability.
IDs remain stable while records exist in this database; they are
not portable across databases or deletion and reinsertion.

## Duplicate handling

The same exact stored link identifies the same collected article.

The uploader trims surrounding whitespace, keeps the first valid
input record for a repeated link, and skips links already stored.
Existing database metadata and legacy subjects are preserved.

URL normalization, redirect resolution, tracking-parameter removal,
and cross-publisher story deduplication are not implemented.
Different URLs may describe the same story.

CSV input has no database ID. Matching it to stored records requires
the exact stored link and verification of the resulting news.id.
Never link records by assuming their numeric IDs correspond.

## Field ownership and legacy columns

Data owns title, link, source, published, and RSS description in news.
Topics owns category in news_articles.
Content owns generated topic summaries and drafts.

In the target workflow:

- news_articles.category is the authoritative assigned classification.
- news.subject is retained for now but must not become a competing
  classification source.
- Content reads original metadata and RSS description from news.
- Duplicated metadata in news_articles is legacy data and must not
  override news metadata in the Content interface.
- news_articles.summary must not substitute for RSS description
  or Content's multi-article topic summaries.

Existing writers and provisional data must be inspected before
changing how legacy fields are maintained. No columns or tables
are renamed or removed by this documentation.

## Topic labels and classification state

The proposed allowed list for final Data and Topics review is the
13-label list used by the inspected classifier:

- AI and LLMs
- AI agents and assistants
- AI automation and workflows
- Software and APIs
- Cloud and DevOps
- Cybersecurity
- Startups and funding
- Robotics and autonomous systems
- Consumer Technology and Wearables
- Technology Events
- Energy and Climate Technology
- Business and Finance
- Other

This replaces the earlier ten-label proposal for review.
Approval of this list must be confirmed before the contract is final.
Readers and writers must use the same agreed labels.

Publisher-provided RSS categories are external metadata and may be
classifier inputs. They are not our assigned classification.

Other means categorization completed without another matching label.
It does not imply human review or approval.

An existing default category of Other alone does not prove that
categorization ran successfully.

The target writer creates an eligible categorized record only after
successful classification. Failed attempts must not create records
that appear completed or overwrite existing assignments.

Existing provisional rows require verification or reclassification
before being treated as successfully categorized. If records are
created before classification, an explicit completion indicator and
eligibility rule must be agreed in #19 and reflected in #26 / #27.
Do not infer completion from category alone.

Existing assignments must not be overwritten unintentionally.
Intentional reclassification must be explicit and documented.

## Content read interface

Content reads successfully categorized articles through a documented
backend query or view joining:

news_articles.news_id = news.id

The interface exposes:

| Output field | Source |
|---|---|
| news_id | news.id |
| title | news.title |
| link | news.link |
| source | news.source |
| published | news.published |
| subject | news_articles.category |
| description | news.description |

The output subject is an interface name for the assigned category.
It is not read from news.subject.

Illustrative target query, usable only after the relationship and
categorized-record eligibility have been implemented and verified:

SELECT
    n.id AS news_id,
    n.title,
    n.link,
    n.source,
    n.published,
    a.category AS subject,
    n.description
FROM public.news AS n
JOIN public.news_articles AS a
    ON a.news_id = n.id;

This join establishes article identity. It does not independently
prove classification completion for legacy or provisional records.
The implemented interface must exclude unverified or failed records
using the agreed classification-state rule.

Missing RSS descriptions must not cause Content reading to fail.
The shared news_id and source link must remain available throughout
selection and summary generation.

### Illustrative interface record

{
  "news_id": 123,
  "title": "Example AI assistant announcement",
  "link": "https://example.com/news/assistant",
  "source": "Example Publisher",
  "published": "2026-10-22T08:00:00Z",
  "subject": "AI agents and assistants",
  "description": ""
}

The ID and article are illustrative. An empty description is valid.

## Publication dates and collection window

published is the publication time, not collection or insertion time.
Exchange timestamps as timezone-aware UTC values, for example:

2026-10-22T08:00:00Z

Z means UTC. PostgreSQL clients may display timestamptz values in a
different session timezone.

The collector accepts supported RSS or ISO publication dates and
converts them to UTC. Missing, blank, invalid, timezone-free, and
future dates are rejected rather than guessed.

The collector retains articles published within the seven days
preceding the start of its run, including the window boundaries.
It applies the same checks to previously saved CSV rows.
The uploader independently validates its input against a seven-day
window and rejects missing, invalid, timezone-free, or future dates.

The collection window is not a database retention policy.
Stored database articles are not automatically deleted.
Any future retention process must consider dependent records and
be separately agreed and implemented.

## RSS descriptions and CSV exchange

Descriptions come from publishers' RSS feeds.
The collector removes HTML formatting, preserves common text
boundaries, decodes HTML character references, and normalizes
whitespace.

Descriptions are not generated summaries or verified full article
content. Their length varies, and missing values become empty strings.
The collector does not fetch article pages to fill them.

CSV exchange uses UTF-8 with BOM and a header row.
Python readers should use utf-8-sig and a CSV parser because values
can contain commas, quotes, and line breaks.

The collector preserves existing CSV descriptions and can fill
missing descriptions from feeds. The current uploader skips existing
database links, so later CSV enrichment does not update stored rows.

## Migration and provisional records

Issue #26 must inspect existing news_articles records, constraints,
and current writers before preparing the migration.

Match records using verified article identity, such as exact links.
Assess unmatched links, duplicates, and ambiguous matches explicitly.
Do not assume matching table IDs and do not delete unmatched records
without explicit approval.

Record a reviewed migration plan before enforcing the target
NOT NULL, UNIQUE, and foreign-key constraints.
Preserve existing data and document how provisional records are
handled.

Commit migration SQL, verification results, and access instructions.
Keep #26 open until implementation and verification are linked.

## Access

Use a backend connection with appropriate permissions.
Credentials belong in local environment variables or deployment
secret configuration, never in Git or frontend code.

RLS is enabled on news. The existing uploader uses a backend secret
key; it does not add client-facing RLS policies.

The relationship and read-interface implementation must document
permissions for both tables and any view or query. Do not assume a
view automatically provides appropriate access controls.

## Generated Content storage

Generated multi-article summaries and drafts are separate from RSS
descriptions and category assignment.

Nedal's generated-output storage proposal remains separate:
https://github.com/Kisslo/novatech-insights/pull/10#issuecomment-6312435947

This contract does not implement or approve those proposed tables.

## Follow-up tracking and acceptance

- #26: table relationship, safe migration, Content read interface,
  access documentation, and verification.
- #19: Python categorization from news into news_articles using news_id,
  classification state, assignment preservation, and error handling.
- #27: Content reading categorized Supabase records, preserving IDs,
  selection behavior, isolated tests, and a read-only dry-run test.

Issue #19 must be aligned with this finalized contract.
Existing implementations should be linked and verified rather than
rebuilt. Unimplemented work stays open in the relevant issue.

Before closing #4:

- [ ] Data and Topics confirm table roles and field ownership.
- [ ] Shared identity, target constraints, and Content mapping are agreed.
- [ ] Topics confirms the explicit allowed label list.
- [ ] Classification completion and provisional-record handling are agreed.
- [ ] Date, description, duplicate, and retention rules are reviewed.
- [ ] Follow-up issues #26, #19, and #27 are linked and aligned.
- [ ] PR #10 is approved and merged.

The integrations do not need to be implemented to complete this
documentation task. Their pending work must remain traceable.