
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

The project is in its initial setup phase. The architecture,
shared development environment, and deployment approach have
not yet been finalized.

n8n has been mentioned as a possible automation tool but has
not been confirmed as a technology choice.

## Proposed Initial Grouping Test

An initial test has been proposed in which news items are
grouped based on their titles.

Proposed core fields:
- title
- link
- source
- publication_date

Kisslo has also identified topic or genre as relevant information.
Its representation and assignment need to be defined.

Title-based grouping is a test proposal, not a decision about
the system's final analysis method.

## Open Questions

- Selection of tools, services, and integrations.
- Storage and handling of news data and generated content.
- Data formats and interfaces between components.
- Documentation of priority search phrases and services.
- Definition and assignment of topics or genres.
- Processes and authority for review, approval, and publication.
- Definition of the results metrics owned by the Data area.
- Shared Python version and dependency management.
- Target environment for deployment and ongoing maintenance.

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

Run the tests from the repository root:

```bash
uv run python -m pytest
```

The tests cover date parsing, date formatting, and RSS description
cleaning. They do not make network requests or connect to a database.

### Continuous Integration

The GitHub Actions workflow in `.github/workflows/ci.yml` runs on pull
requests targeting `main` and on pushes to `main`. It also supports
manual runs.

CI installs dependencies from `uv.lock` and runs:

```bash
uv run --locked ruff check .
uv run --locked python -m pytest
```

Formatting is checked locally using the command in the Code Quality
section; it is not currently checked in CI.

### Local Setup

Install uv before following these steps.

From the repository root, create or synchronize the local environment:

```bash
uv sync --locked
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

Declare runtime dependencies in `pyproject.toml` usiNo conng:

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

Branch protection has been requested and is pending configuration.

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
the pull request.

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
Results are saved to `data/news.csv` is local and ignored by Git. Run the collector to create or update it.

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

The current collector uses `published` for the publication date;
the proposed grouping fields above call it `publication_date`.
The shared field name still needs to be agreed.

The `subject` field is currently left blank for new articles.
The collector saves the RSS feed's `description` as plain text,
with HTML formatting removed and whitespace normalized.
Missing descriptions are saved as empty values.

Existing articles with empty descriptions are updated when they
are still available in the feed. Existing subjects are preserved.

Descriptions are supplied by publishers, not generated or verified
by our system. Their length varies, and the collector does not
shorten them or fetch article pages.
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
Row Level Security is enabled. The backend secret key bypasses RLS
and must never be included in frontend code or committed to Git.

The seven-day filter applies to upload input. Previously uploaded
articles are not automatically deleted when they become older.

If an upload fails, earlier batches may already be saved.
Rerunning the command skips existing links.


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