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

With `previous_days = 7`, the counting windows are:

```text
recent:   now - 1 day < published <= now
previous: now - 8 days < published <= now - 1 day
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
| `previous_days` | `7` | Velocity comparison period before the latest day |
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
