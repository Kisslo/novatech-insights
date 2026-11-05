# Topic ranking

`src/rank_topics.py` calculates topic scores from article data and returns topics in score order.

## Input

`rank_topics()` receives:

- Topics with an integer `id` and an iterable of `articles`.
- A time-zone-aware `now` used as the calculation time.
- `source_weights`: a mapping of source names to numeric weights.
- `swedish_sources`: the source names used to identify Swedish coverage.
- Scoring parameters and an optional `top_n` result limit.

Each article contains `id`, `source`, and `published`. Publication timestamps must be ISO strings with an explicit time zone and are converted to UTC.

## Article score

Each article contributes its source weight multiplied by its remaining time weight:

```text
time_weight = 0.5 ** (age_days / half_life_days)
article_contribution = source_weight * time_weight
article_score = sum(article_contribution)
```

With the default three-day half-life, an article retains half its time weight after three days and one quarter after six days.

Source-weight matching ignores case and surrounding whitespace. Sources without a configured match use `default_weight`, which defaults to `1.0`.

Article score therefore increases with article volume, freshness, and configured source weight.

## Source breadth

Two source metrics are calculated:

- `source_count`: the integer number of distinct non-empty source values.
- `source_breadth`: the sum of each distinct source's freshest article time weight.

```text
source_breadth = sum(freshest_time_weight_for_each_source)
```

A source with a fresh article contributes `1.0`. A source whose freshest article is three days old contributes `0.5` with the default half-life. Additional articles from the same source do not add to source breadth.

Both source metrics use exact source values. Case and whitespace normalization used for source weights is not applied to these metrics.

The score uses `source_breadth`; `source_count` remains available in the output metrics.

## Velocity

Velocity compares coverage in the latest day with the daily average of the preceding period:

```text
daily_average = previous_count / previous_days
velocity = recent_count / max(daily_average, 1)
```

With `previous_days = 6`, the counting windows are:

```text
recent:   now - 1 day < published <= now
previous: now - 7 days < published <= now - 1 day
```

The denominator is at least `1`. When the previous daily average is below `1`, velocity equals the number of articles in the latest day.

The output includes `velocity`, `recent_count`, `previous_count`, and `previous_days`.

## Bounded breadth and velocity bonuses

Breadth and velocity use the same saturation function:

```text
bonus_factor = max_bonus * value / (scale + value)
```

A value of zero gives no bonus. When `value` equals `scale`, the factor equals half of `max_bonus`. As the value increases, the factor approaches `max_bonus` with diminishing additional increases.

```text
breadth_bonus_factor = (
    max_breadth_bonus * source_breadth
    / (breadth_scale + source_breadth)
)

velocity_bonus_factor = (
    max_velocity_bonus * velocity
    / (velocity_scale + velocity)
)
```

The factors multiply the article score to produce the two bonus contributions.

## Swedish bonus

Articles whose sources match `swedish_sources` contribute to `swedish_article_score`. Matching ignores case and surrounding whitespace.

```text
swedish_article_score = sum(article_contributions_from_swedish_sources)
swedish_bonus = swedish_weight * swedish_article_score
```

The bonus uses those articles' own source weights and time decay.

`swedish_signal` is also returned: `1.0` when a matching source is present, otherwise `0.0`. The score calculation uses `swedish_article_score`, not this indicator.

## Final score

```text
score = article_score * (
    1 + breadth_bonus_factor + velocity_bonus_factor
) + swedish_bonus
```

`calculate_topic_score_contributions()` calculates four contributions:

| Contribution | Calculation |
|---|---|
| `base` | `article_score` |
| `breadth` | `article_score * breadth_bonus_factor` |
| `velocity` | `article_score * velocity_bonus_factor` |
| `swedish` | `swedish_weight * swedish_article_score` |

The final score is their sum. The same contribution function supplies the score breakdown.

With the default bonus maxima, breadth and velocity each add up to 100% of article score. Together, the base and these two bonuses have a multiplier bounded by `3`, before the Swedish bonus. Article score itself is the sum of article contributions.

## Default parameters

| Parameter | Default | Meaning |
|---|---:|---|
| `half_life_days` | `3` | Half-life used by article contributions and source breadth |
| `default_weight` | `1.0` | Source weight for sources without a configured match |
| `previous_days` | `6` | Velocity comparison period before the latest day |
| `max_breadth_bonus` | `1.0` | Maximum additional breadth factor |
| `breadth_scale` | `3.0` | Weighted source breadth giving half the maximum breadth factor |
| `max_velocity_bonus` | `1.0` | Maximum additional velocity factor |
| `velocity_scale` | `5.0` | Velocity giving half the maximum velocity factor |
| `swedish_weight` | `0.50` | Multiplier for Swedish article contributions |
| `score_version` | `preliminary-v2` | Identifier included with the calculated score |
| `top_n` | `None` | Return all ranked topics unless a limit is supplied |

Callers can supply other values. An explicitly supplied `score_version` is preserved.

## Duplicate and timestamp handling

Within each topic, articles with the same `id` are counted once. The first occurrence is retained. The same article can contribute to multiple topics.

Publication times up to five minutes ahead of `now` are treated as `now` during calculation. The article's original metadata is not modified.

Missing or invalid publication timestamps, or timestamps more than five minutes ahead, raise `InvalidPublicationTimeError`. In `rank_topics()`, these articles are skipped with a logged warning. Topics with no valid articles are also skipped. Lower-level calculation functions raise the error to their caller.

`now` must contain time-zone information. Topic IDs must be integers, not booleans, and must be unique in the input. `top_n`, when supplied, must be a positive integer, not a boolean.

## Ordering and output

Results are sorted by descending score, then ascending topic ID for equal scores. The `top_n` limit is applied after sorting.

Each returned topic contains:

| Field | Content |
|---|---|
| `id` | Topic identifier |
| `score` | Total topic score |
| `score_calculated_at` | Calculation time as a UTC ISO timestamp |
| `score_version` | Supplied or default scoring version |
| `score_breakdown` | Measurements, scoring parameters, contributions, and calculation configuration |

`score_breakdown` contains:

- `metrics`: article score, article count, individual article contributions, source count, weighted source breadth, velocity and its counts, Swedish signal, and Swedish article score.
- `weights`: `max_breadth_bonus`, `breadth_scale`, `max_velocity_bonus`, `velocity_scale`, and `swedish`.
- `contributions`: the `base`, `breadth`, `velocity`, and `swedish` score contributions.
- `config`: `half_life_days`, `default_source_weight`, `previous_days`, `future_tolerance_seconds`, `source_weights`, and `swedish_sources`.

Individual article contributions use `news_id` to identify the input article. They include `source_weight`, `time_weight`, and `contribution`.

## Configuration and Supabase adapter

The first integration uses [`config/ranking.json`](../config/ranking.json) for
the adjustable ranking settings. Its defaults preserve the values above,
including `previous_days = 6` and an empty `source_weights` object. An empty
source-weight mapping means that every source uses the default weight `1.0`.

The adapter in `src/rank_topics_supabase.py` reads all rows from `topics`,
`topic_articles`, and `news` with stable offset pagination. It uses every
article linked through `topic_articles`; `topic_top_articles` is a
presentation view and is not used for ranking. Article IDs from `news.id` are
retained in the ranking input and breakdown.

Swedish sources are derived at runtime from rows in the shared
`data/sources.csv` registry whose `language` is `sv`. This is a source-based
signal using the registry's language marker, not an assessment of an
individual article's geographic relevance. Source matching uses the shared
`normalize_source()` function.

The adapter validates the complete read before any write. It uses one
timezone-aware `now` for the whole run. Without `--write`, it is read-only.
With explicit `--write`, it updates only `score`, `score_calculated_at`,
`score_version`, and `score_breakdown`, one topic at a time. A topic with no
valid articles has those fields cleared to `NULL`. An unexpected calculation
error leaves that topic's previous result untouched. Read failures abort before
any update; isolated topic and write failures are reported in the run summary.

The adapter depends on the schema and permissions from PR #39. Live execution
also requires the migrations to be applied and a server-side key with the
appropriate backend permissions. Local tests use mocked API responses only.

At the adapter boundary, ranking receives a separate article representation:
`source` contains `normalize_source(source)`, while the original article,
including `news.id` and stored source values, is not modified. A non-NULL
`source_normalized` must match the calculated identity; a mismatch aborts before
writing. A NULL stored value is allowed, but is reported as a warning.
Normalization affects source breadth and therefore can change the final score
when spelling, case, or whitespace variants of one source are merged into one
identity.

Pagination continues until an empty page, rather than treating a short page as
the end. This handles APIs that impose a smaller server-side page size than
requested. Offset pagination can still observe duplicates, omissions, or
inconsistent snapshots if rows are inserted or removed during the run; live
execution should therefore use a stable dataset or rerun after concurrent
changes.

## Running the Supabase adapter

The adapter requires these environment variables:

- `SUPABASE_URL`: the Supabase project URL.
- `SUPABASE_KEY`: a server-side backend key with the permissions described
  below. Keep this key private.

They can be placed in the project's local `.env` file. The adapter loads that
file when it is run as a script. Do not commit `.env` or expose
`SUPABASE_KEY` to client-side code.

The default command is read-only:

```bash
uv run --locked python src/rank_topics_supabase.py
```

It reads and calculates rankings but does not update the database. To
explicitly save results:

```bash
uv run --locked python src/rank_topics_supabase.py --write
```

With `--write`, the adapter updates only these four fields in `topics`,
together for each topic:

- `score`
- `score_calculated_at`
- `score_version`
- `score_breakdown`

### Database prerequisites

Before live ranking, apply the existing topic-storage migrations in order:

1. `sql/002_create_topic_storage.sql`
2. `sql/003_create_topics_and_links.sql`
3. `sql/004_create_topic_read_views.sql`
4. `sql/005_save_topic_group.sql`
5. `sql/006_topic_backend_permissions.sql`

Migration 006 provides the backend `service_role` access needed by the
adapter: read access to `news`, `topics`, `topic_articles` and the topic read
views, plus update access to the four ranking fields. `service_role` bypasses
RLS but still requires these SQL grants. The role and live REST access must be
verified in the target Supabase project; local SQL permission tests do not
prove live API access.

Existing articles must first be normalized and verified using the repository's
source-key backfill. Complete and verify that backfill before applying
`sql/007_require_normalized_sources.sql`. In particular, confirm that the
required `source_normalized` values are present and that the NULL-count query
returns zero. Migration 007 must not be applied before this verified backfill.

After migration 007, verify the live API reads and the backend update
permissions before enabling `--write`. The ranking adapter does not perform
the backfill and does not repair source-normalization mismatches.
