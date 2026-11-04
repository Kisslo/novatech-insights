# Novatech Insights

A system for collecting relevant news and developing it into content
for the Novatech Solutions website and LinkedIn.

The system will support an editorial workflow in which news is
grouped, prioritized, and summarized to support the creation of
articles, LinkedIn posts, and videos.

## Purpose

Increase Novatech Solutions' visibility on Google and LinkedIn
through relevant content based on current news and the company's
perspective.

## Planned Functionality

- Collect news information from selected sources.
- Identify and handle duplicates.
- Group news into topics.
- Summarize news to support editorial review.
- Produce articles for novatech-solutions.se and short LinkedIn
  posts based on Kisslo's arguments.
- Verify the sources used to develop the content.
- Support a workflow for review, approval, and publication.
- Rank topics using a model trained on Kisslo's ratings.
- Evaluate the model based on the proportion of suggestions
  Kisslo actually uses.
- Create short videos from approved articles using Videofy.

## Requirements and Constraints

- RSS descriptions may be stored as agreed by the team.
  Other source article text must not be copied into the system.
- LinkedIn must not be read automatically.
- Topic or genre information must be considered when defining
  the news data structure, based on Kisslo's feedback.
- News collection and topic grouping must account for the four
  to five search phrases and services Kisslo has identified as
  priorities. The specific list needs to be documented and
  must support future expansion.
- The Videofy integration must include Python code that sends
  articles to Videofy and a customer configuration file in JSON
  containing a logo, voice settings, and AI instructions.

## Delivery Milestones

### Week 1 — Project Foundation

Week 1 is allocated to establishing the project foundation.

Proposed scope:

- Prepare the shared repository and project documentation.
- Establish a common foundation for local development
  and configuration.
- Clarify responsibilities and how information will be
  transferred between components.

Stretch goal: complete an initial successful retrieval of a
news article from a selected source.

The scope and acceptance criteria for successful retrieval
need to be defined before the test is carried out.

### By the End of Week 2

- At least 30 news sources.
- The first week's news grouped into topics.

### From Week 5

- Each approved article must also be turned into a short
  video using Videofy.

## Preliminary Responsibility Assignment

| Area | Assigned to | Scope |
|---|---|---|
| Data | Nosheen | News retrieval, duplicate handling, and results measurement. Python code for transferring articles to Videofy. |
| Topics | Mathias, Turker | News grouping and an ML model that ranks topics based on Kisslo's ratings. Evaluation of the ranking. |
| Content | Nedal | Summaries, content drafts, source verification, and the publication workflow. Customer configuration file in JSON for Videofy. |

The areas follow the project brief. The assignment of individuals
is preliminary.

Interfaces between components and responsibility for shared
components need to be clarified. Responsibility for the publication
workflow does not automatically grant authority to approve or
publish content.

## Status

News collection, CSV classification, Supabase news uploading,
semantic grouping, topic summaries and topic-label output have
implementations in the repository.

Draft PR #39 adds topic storage, read views, optional group saving
and shared backend permissions. Local and CI tests cover these
changes, but migrations 002–006 have not been applied to Supabase.

Live grouping-to-ranking-to-reader integration and deployment
verification remain pending.

See [the data contract](docs/article-data-contract.md) and
[verification results](docs/topic-storage-verification.md)
for the current implementation scope and limitations.

## Proposed Initial Grouping Test

The initial proposal grouped news items based on their titles.

Its proposed core fields were:

- title
- link
- source
- publication_date

The implemented article contract uses `published` for the
publication timestamp. Semantic grouping now uses article titles
and RSS descriptions.

The initial title-only proposal is historical context, not the
current grouping implementation.

## Open Questions

- Selection of tools, services, and integrations.
- Storage and handling of generated content.
- Documentation of priority search phrases and services.
- Topic identity, regrouping and retirement of older groups.
- Processes and authority for review, approval, and publication.
- Definition of the results metrics owned by the Data area.
- Target environment for deployment and ongoing maintenance.

See [the data contract](docs/article-data-contract.md) for
remaining storage and interface decisions.

## Code Quality

Ruff linting and formatting rules are configured in `pyproject.toml`.

Run these checks from the repository root:

```bash
uv run ruff check .
uv run ruff format --check .
```

These commands check the code without modifying files.
To apply formatting, run:

```bash
uv run ruff format .
```

### Tests

Run the Python tests from the repository root:

```bash
uv run python -m pytest
```

The tests cover collection, storage request handling, grouping,
summaries, topic labels and optional group saving. API interactions
are tested using fake responses rather than live credentials.

Separate SQL tests in `sql/` exercise migrations, constraints,
read views, group saving and database permissions in PostgreSQL.

### Continuous Integration

The GitHub Actions workflow in `.github/workflows/ci.yml` runs on pull
requests targeting `main` and on pushes to `main`. It also supports
manual runs.

CI installs dependencies from `uv.lock` and runs:

```bash
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked python -m pytest
```

You can run the same commands locally from the repository root.
The linting and formatting checks do not modify files.
A failed check or test causes CI to fail.

The database jobs use these container image tags:

- `pgvector/pgvector:0.8.2-pg17`
- `pgvector/pgvector:pg17`

They test migrations and SQL assertions in an empty database and
a separate database with simulated Supabase default grants.
Automatic-grant removal is checked before migration 006 applies
the backend grants. Backend tests then verify those actual grants.

These tests do not connect to or modify the team's Supabase project.

To fix formatting locally, run:

```bash
uv run --locked ruff format .
```

Commit any resulting formatting changes before pushing.

### Local Setup

Install uv before following these steps.

From the repository root, create or synchronize the local environment:

```bash
uv sync --locked --dev
```

This command creates `.venv` if needed and installs dependencies
from `uv.lock`. It fails if the lockfile needs to be updated.

Verify the Python version used by the project:

```bash
uv run python --version
```

Run project commands through `uv run` to use the project environment.
Manual activation of `.venv` is not required.

### Environment Configuration

`.env.example` documents the available configuration variables.
Supabase storage uses SUPABASE_URL and SUPABASE_KEY.
Set SUPABASE_URL to the project base URL, without /rest/v1.
Set SUPABASE_KEY to a secret API key for backend use only.
Keep real credentials in the ignored .env file.

When local configuration is needed, copy the template:

```bash
cp .env.example .env
```

Add local values to `.env`, never to `.env.example`.

Do not commit API keys, passwords, customer data, or other sensitive
information. `.env` is ignored by Git; `.env.example` must contain
only safe placeholders and documentation.

### Dependencies

Declare runtime dependencies in `pyproject.toml` using:

```bash
uv add <package>
```

Declare development dependencies using:

```bash
uv add --dev <package>
```

Commit both `pyproject.toml` and `uv.lock` when dependencies change.
Do not edit `uv.lock` manually or commit `.venv`.

Ruff and pytest are included as development dependencies.

Verify that the tools are available in the project environment:

```bash
uv run ruff --version
uv run python -m pytest --version
```

Ruff linting rules are configured in `pyproject.toml`, and automated
tests are located in `tests/`.

Run the tests from the repository root:

```bash
uv run python -m pytest
```

Use `python -m pytest` rather than `pytest` directly. This adds the
current directory to Python's import search path, allowing the tests
to import project code such as `src.collect_news`.

## Contribution Workflow

- Create a separate branch for each logically scoped change.
- Submit changes through a pull request targeting `main`.
- Have another contributor review the changes before merging.
- Verify the changes in the shared project environment.
- Use Conventional Commits, for example:
  `docs: update development instructions`.

Follow the repository's current branch protection and review
requirements when merging.

### Tests in Pull Requests

The contributor implementing a change is responsible for adding or
updating relevant pytest tests in the same pull request.

- Test new or changed behavior, including relevant edge cases and errors.
- When fixing a bug, add a regression test where practical.
- Keep automated unit tests independent of live services and credentials.
- Place tests in `tests/`, using filenames such as `test_collect_news.py`.

Run the tests from the repository root before requesting review:

```bash
uv run python -m pytest
```

If automated tests are not relevant, briefly explain why in the pull
request description and describe how the change was verified.

### Documentation in Pull Requests

Update relevant documentation in the same pull request when a change
affects setup, configuration, usage, interfaces, or documented behavior.

Update README when the project's entry-point information changes.
Update `.env.example` when configuration variables are added,
changed, or removed.

A documentation change is not required for every commit or pull request.
If documentation is unaffected, state that no update is needed
in the pull request description.

### Reviewing and Merging

The reviewer should check that:

- The changes match the purpose and scope of the pull request.
- Relevant tests are included and CI checks pass.
- Documentation matches the proposed changes.
- No credentials or other sensitive information are included.

If everything looks good and CI checks pass, approve and merge
the pull request in accordance with the repository's review requirements.

If changes are needed, comment on the relevant lines in the
Files changed tab and submit the review with Request changes.
For feedback that is not tied to a specific line, leave a general
review comment.

The contributor should address the feedback and push updates to
the same branch. Review the updated changes and confirm that CI
checks pass before merging.

## News Collection

Run the collector from the repository root:

```powershell
uv run python src/collect_news.py
```

Sources are configured in `data/sources.csv`.
Results are saved to `data/news.csv`, which is local and ignored by Git.
Run the collector to create or update it.

- Supports RSS feeds with `channel/item` elements.
- Prevents duplicates by checking the exact article link.
- Stores publication dates in ISO 8601 format in UTC,
  for example `2026-10-15T09:30:00Z`.
- Keeps only articles published within the last seven days.
- Skips articles with missing, invalid, timezone-free,
  or future publication dates.
- Applies the same checks to previously saved articles.
- Saves articles with the newest first.

Change `MAX_AGE_DAYS` in `src/collect_news.py` to adjust
the time window.

Output columns: `title`, `link`, `source`, `published`, `subject`, `description`.

The shared article contract uses `published` for the publication date.
See [the data contract](docs/article-data-contract.md).

The `subject` field is currently left blank for new articles.
The collector saves the RSS feed's `description` as plain text,
with HTML formatting removed and whitespace normalized.
Missing descriptions are saved as empty values.

Existing articles with empty descriptions are updated when they
are still available in the feed. Existing subjects are preserved.

Descriptions are supplied by publishers, not generated or verified
by our system. Their length varies, and the collector does not
shorten them or fetch article pages.

## Topic Classification

The topic classifier assigns news articles to topic categories using
the keywords defined in `src/group_topics.py`.

These legacy `subject` categories are separate from semantic
topic membership in `public.topic_articles`.

### Run the classifier

Run from the repository root:

```powershell
uv run python src/group_topics.py
```

The script reads `data/news.csv` and writes classified articles to
`data/news_with_topics.csv`. The input CSV must contain the columns
`title`, `link`, `source`, `published`, and `subject`. The `description`
column is used when available; older CSV files without it are supported.

Existing non-empty `subject` values are preserved during normal runs.
Only articles with an empty `subject` are classified.

To intentionally reclassify all articles, including those with an
existing subject, run:

```powershell
uv run python src/group_topics.py --reclassify
```

### Test topic classification

Run the topic classification tests:

```powershell
uv run --locked python -m pytest tests/test_group_topics.py
```

Run all tests and lint checks:

```powershell
uv run --locked python -m pytest
uv run --locked ruff check .
```

## Supabase News Storage

Validate the collected CSV without changing local or remote data:

```powershell
uv run python src/store_news.py
```

Upload valid articles to the `public.news` table:

```powershell
uv run python src/store_news.py --upload
```

The uploader:

- Reads `data/news.csv`.
- Requires title, link, source, and a valid publication timestamp.
- Accepts only timezone-aware dates within the last seven days.
- Converts publication timestamps to UTC.
- Removes duplicate links from the upload input.
- Uploads in batches of up to 100 articles through the REST API.
- Skips links already stored in Supabase without updating their fields.
- Reports inserted articles and skipped existing links.
- Leaves the CSV and the separate `news_articles` table unchanged.

The database generates `id` and `collected_at`.
A unique constraint on `link` prevents duplicate articles.
Row Level Security is enabled. The backend secret key uses
`service_role`, which bypasses RLS but still requires SQL grants.
The key must never be included in frontend code or committed to Git.

The seven-day filter applies to upload input. Previously uploaded
articles are not automatically deleted when they become older.

If an upload fails, earlier batches may already be saved.
Rerunning the command skips existing links.

## Semantic News Grouping

The project includes two scripts for semantic news analysis:

- `src/embed_news.py` finds similar news articles using multilingual
  sentence embeddings.
- `src/group_news.py` groups related articles into news events using
  cosine similarity and constrained complete-link clustering.

### Requirements

The scripts require the following environment variables in `.env`:

- `SUPABASE_URL`: The Supabase project URL.
- `SUPABASE_KEY`: The Supabase backend API key.

See the Environment Configuration section for setup instructions.
Never commit real credentials.

The scripts use the multilingual Sentence Transformers model:

`sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`

The model is approximately 470 MB and is downloaded automatically
from Hugging Face the first time either script is run. An internet
connection is required for the initial download. Subsequent runs
reuse the locally cached model.

### Generate article embeddings and find similar articles

Run from the repository root:

```powershell
uv run python src/embed_news.py
```

The script retrieves articles from Supabase, generates embeddings,
and identifies the most similar article pairs from different sources.

### Group related news articles

Run from the repository root:

```powershell
uv run python src/group_news.py
```

By default, this reads articles and displays groups without
writing to the database.

The grouping script:

- Retrieves articles using a seven-day publication-date cutoff.
- Excludes articles without a publication date through the database
  date filter.
- Deduplicates articles locally while preserving their database IDs.
- Groups semantically similar articles from different sources.
- Requires articles in a group to meet the similarity threshold.
- Limits the publication-date spread within each group to seven days.

### Save groups to the database

Saving requires the explicit `--save` option:

```powershell
uv run python src/group_news.py --save
```

Before using this option, the target database must have migrations
002–006 applied in order and the required backend permissions.
The existing `public.news` table must already be present.

These migrations have not yet been applied to the team's Supabase
project. Live REST API saving remains to be verified.

The command uses `SUPABASE_URL` and `SUPABASE_KEY` from `.env`.
Check that they identify the intended database before saving.

For each group, the script calls `public.save_topic_group(bigint[])`
through the Supabase REST API:

- Saves a topic and all its article links together.
- Reuses an existing topic with exactly the same article-ID set.
- Preserves existing labels and ranking fields when reusing a topic.
- Creates a new topic when no exact article-ID set matches.
- Saves all groups and their full memberships, regardless of
  terminal display limits.

Each group is saved in a separate transaction. If a later save
fails, earlier groups may already be committed. The script stops
processing subsequent groups.

A connection failure may leave the current request's outcome
uncertain. Retrying the same article-ID set reuses a topic that
was successfully saved.

Older or overlapping topics are not automatically replaced or
deleted. Their lifecycle still requires team agreement.

Grouping and saving do not modify original news records.
The save operation does not store embeddings or generate scores
or labels.

See [the data contract](docs/article-data-contract.md) and
[verification results](docs/topic-storage-verification.md)
for permissions, tested behavior and remaining limitations.

## Topic Summaries

`src/summarize_topic.py` creates one Swedish topic summary from articles
in `data/news.csv` using the Claude API.

```powershell
uv run python src/collect_news.py
uv run python src/summarize_topic.py --keyword agent --fetch --limit 3 --dry-run
uv run python src/summarize_topic.py --keyword agent --fetch --limit 3
```

`--dry-run` shows the selected articles and estimated cost without calling
Claude. A real run needs `ANTHROPIC_API_KEY` in `.env`. Use `--help` to see
all options.

Summaries are stored temporarily as Markdown files in `output/summaries/`,
which is ignored by Git. Database storage is planned in issue #5.

## Topic Labels and Top-N List

`src/label_topics.py` reads ranked topics with their best articles
(max 3 per topic), asks Claude for a Swedish label, a short explanation
of why the topic matters (`why_relevant_sv`) and a relevance rating from
1 to 5 (`llm_relevance`), and writes a top-N list as Markdown (issue #27).

```powershell
uv run python src/label_topics.py --top 5 --dry-run
uv run python src/label_topics.py --top 5
uv run python src/label_topics.py --source supabase --top 20 --dry-run
uv run python src/label_topics.py --source supabase --top 20 --save
```

- `--source fixture` (default) reads `tests/fixtures/sample_topics.json`.
- `--source supabase` reads two views through the Supabase REST API.
  Their names are set in `.env` with `TOPICS_OVERVIEW_VIEW`
  (default `topic_overview`) and `TOPICS_ARTICLES_VIEW`
  (default `topic_top_articles`). The views are part of issue #26.
  Without `--save`, Supabase is only read.
- `--top` sets the number of topics (default 20, e.g. 5 for Telegram).
- `--dry-run` shows the prompts, a preview of the list and the estimated
  cost without calling Claude. It does not need `ANTHROPIC_API_KEY`.
  With `--source fixture`, no API credentials are needed.
  With `--source supabase`, `SUPABASE_URL` and `SUPABASE_KEY` are
  still required to read the database. Nothing is written.
- `--save` (only with `--source supabase`, issue #42) writes `label`,
  `why_relevant_sv` and `llm_relevance` to the `topics` table
  (`TOPICS_TABLE` in `.env`). Topics that already have all three values
  are not sent to Claude again. Nothing else in `topics` is changed.
- `--relabel` (with `--save`) labels and saves every listed topic again.

A real run makes one Claude call per topic and needs `ANTHROPIC_API_KEY`
in `.env`. It stops before any call if the estimated cost is above
0.5 USD. A topic that fails is reported in the terminal and in the list,
and the run continues with the next topic. A topic with invalid data
(for example an article without title, source or link) is skipped and
reported; with `--source supabase` a few extra topics are read, so this
does not make the list shorter than `--top`. If saving fails for one
topic, it is reported and the next topic is saved.

The list is saved in `output/top<N>_<date>_<time>.md`, which is ignored
by Git. Each topic shows its rank, label, score, number of sources and
articles, AI relevance and up to three article links with their `news_id`.

`--save` needs UPDATE permission on `topics.label`, `why_relevant_sv` and
`--save` needs UPDATE permission on `topics.label`, `why_relevant_sv` and
`llm_relevance` for the backend key (granted in `sql/006_topic_backend_permissions.sql`).

## Telegram API

`src/telegram_api.py` is a small FastAPI app that n8n calls to get the
top topics as ready-to-send Telegram messages with the buttons **Skriv**
and **Skippa** (issue #42). It only reads labelled topics and never calls
Claude. The message text is built by `src/telegram_format.py`.

```powershell
uv run uvicorn telegram_api:app --app-dir src --port 8000
```

Requests need the header `X-API-Key` with `TELEGRAM_API_KEY` from `.env`.
`TELEGRAM_SOURCE` chooses `fixture` (default) or `supabase`.
See [docs/telegram-api.md](docs/telegram-api.md) for the response format,
errors, the tunnel used during development and the n8n settings.