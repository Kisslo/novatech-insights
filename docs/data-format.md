# News Data Format for Topic Grouping

Status: Proposed agreement for issue #4.
Data and Topics review is required before this agreement is final.

This document describes the CSV output implemented in PR #1.
It does not introduce changes to the collector.

## File format

- File: `data/news.csv`
- Encoding: UTF-8 with BOM. Python readers should use `utf-8-sig`.
- Delimiter: comma.
- The first row contains column names.
- Each record represents one collected article.
- Use a CSV parser because headlines may contain commas or quotes.

Column order:

```csv
title,link,source,published,subject
```

## Field definitions

| Field | Meaning | Empty values | Assigned by |
|---|---|---|---|
| `title` | Headline supplied by the RSS feed. | Not allowed; the collector skips items without a title. | Data collector |
| `link` | Article URL supplied by the feed. Used for exact-link deduplication. | Not allowed; the collector skips items without a link. | Data collector |
| `source` | Source name from the `name` column in `data/sources.csv`. | Required by this proposed agreement. The collector does not currently validate that source names are non-empty. | Data through source configuration |
| `published` | Article publication timestamp in ISO 8601 format, in UTC. | Not allowed in current output; missing or invalid dates are skipped. | Data collector |
| `subject` | One topic label assigned to the article. | Allowed; empty means not grouped yet. | Topics: Mathias and Turker |

The CSV field name is `published`. Readers should use this name,
rather than the earlier proposed name `publication_date`.

## Publication dates and collection window

Example timestamp: `2026-10-15T09:30:00Z`.

`Z` means UTC. This is the publication time, not the collection time.

The collector already converts supported RSS and ISO dates to UTC.
It skips missing, invalid, timezone-free, and future dates.

The current collection window is the seven days preceding the
start of each run. The same filter applies to previously saved rows.
Articles are saved newest first.

The CSV is a rolling collection, not a permanent archive.
Topic grouping should parse timestamps as timezone-aware dates.

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

## Example record

Illustrative example of an ungrouped article:

```csv
title,link,source,published,subject
Example: New open-source LLM released,https://example.com/article,Example Source,2026-10-15T09:30:00Z,
```

Topics could assign `AI and LLMs` after reviewing this article.
The example date illustrates the format; it is not a permanent
test of eligibility for the rolling seven-day window.

## Interpretation by topic grouping

- Read records with a CSV parser.
- Use `title` as input for the proposed initial title-based test.
- Retain `link` and `source` for traceability.
- Treat exact matching links as the same collected article.
- Different URLs may still describe the same story; the collector
  does not detect that kind of duplication.
- Treat empty subjects as pending grouping.
- Flag records missing required fields rather than guessing values.

The collector currently saves only the five documented fields.
Descriptions and full article text are not included.

## Separate follow-up work

- Validate non-empty source names in the collector.
- Review existing manual subject labels against the agreed list.
- Agree where grouping results are stored and how they are passed
  between components. Avoid concurrent writes to `data/news.csv`.
- Decide whether grouped records need storage beyond seven days.
- Clarify whether short RSS descriptions are permitted by the
  source-text rule before implementing a description field.

UTC conversion is already implemented in PR #1 and does not need
a new implementation issue.

## Review checklist

- [ ] Data has reviewed the field definitions and current behavior.
- [ ] Topics has reviewed empty-value handling and subject ownership.
- [ ] Topics has confirmed the initial topic list.
- [ ] Required implementation changes are recorded as follow-up work.