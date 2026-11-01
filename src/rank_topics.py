from datetime import datetime, timedelta, timezone


def parse_publication_time(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("published must be a non-empty ISO timestamp")

    published = datetime.fromisoformat(value.strip())

    if published.tzinfo is None:
        raise ValueError("published must include a timezone")

    return published.astimezone(timezone.utc)


def count_distinct_sources(articles):
    sources = set()

    for article in articles:
        source = article.get("source")
        if source:
            sources.add(source)

    return len(sources)


def calculate_time_decay(age_days, half_life_days):
    if half_life_days <= 0:
        raise ValueError("half_life_days must be greater than zero")

    if age_days < 0:
        raise ValueError("age_days must not be negative")

    return 0.5 ** (age_days / half_life_days)


def calculate_velocity(recent_count, previous_count, previous_days=7):
    if recent_count < 0 or previous_count < 0:
        raise ValueError("article counts must not be negative")

    if previous_days <= 0:
        raise ValueError("previous_days must be greater than zero")

    daily_average = previous_count / previous_days
    return recent_count / max(daily_average, 1)


def count_velocity_articles(articles, now, previous_days=7):
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must include a timezone")

    if previous_days <= 0:
        raise ValueError("previous_days must be greater than zero")

    recent_start = now - timedelta(days=1)
    previous_start = recent_start - timedelta(days=previous_days)

    recent_count = 0
    previous_count = 0
    seen_ids = set()

    for article in articles:
        article_id = article["id"]
        if article_id in seen_ids:
            continue
        seen_ids.add(article_id)

        published = parse_publication_time(article.get("published"))

        if recent_start < published <= now:
            recent_count += 1
        elif previous_start < published <= recent_start:
            previous_count += 1

    return recent_count, previous_count


def calculate_topic_velocity(articles, now, previous_days=7):
    recent_count, previous_count = count_velocity_articles(articles, now, previous_days)

    velocity = calculate_velocity(recent_count, previous_count, previous_days)

    return {
        "velocity": velocity,
        "recent_count": recent_count,
        "previous_count": previous_count,
        "previous_days": previous_days,
    }


def calculate_swedish_signal(articles, swedish_sources):
    normalized_sources = {
        source.strip().casefold()
        for source in swedish_sources
        if source and source.strip()
    }

    for article in articles:
        source = article.get("source")
        if source and source.strip().casefold() in normalized_sources:
            return 1.0

    return 0.0


def get_source_weight(source, source_weights, default_weight=1.0):
    if default_weight < 0:
        raise ValueError("default_weight must not be negative")

    normalized_weights = {}

    for name, weight in source_weights.items():
        if weight < 0:
            raise ValueError("source weights must not be negative")

        normalized_name = name.strip().casefold()
        normalized_weights[normalized_name] = weight

    normalized_source = (source or "").strip().casefold()

    return normalized_weights.get(normalized_source, default_weight)


def calculate_article_contribution(
    article,
    now,
    source_weights,
    half_life_days=3,
    default_weight=1.0,
):
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must include a timezone")

    published = parse_publication_time(article.get("published"))
    age_days = (now - published).total_seconds() / 86400

    source_weight = get_source_weight(
        article.get("source"), source_weights, default_weight
    )
    time_weight = calculate_time_decay(age_days, half_life_days)

    return {
        "source_weight": source_weight,
        "time_weight": time_weight,
        "contribution": source_weight * time_weight,
    }


def calculate_topic_article_score(
    articles,
    now,
    source_weights,
    half_life_days=3,
    default_weight=1.0,
):
    seen_ids = set()
    contributions = []

    for article in articles:
        article_id = article["id"]
        if article_id in seen_ids:
            continue
        seen_ids.add(article_id)

        result = calculate_article_contribution(
            article,
            now,
            source_weights,
            half_life_days,
            default_weight,
        )

        contributions.append({"news_id": article_id, **result})

    return {
        "article_score": sum(item["contribution"] for item in contributions),
        "article_count": len(contributions),
        "contributions": contributions,
    }


def calculate_topic_metrics(
    articles,
    now,
    source_weights,
    swedish_sources,
    half_life_days=3,
    default_weight=1.0,
    previous_days=7,
):
    articles = list(articles)

    article_result = calculate_topic_article_score(
        articles,
        now,
        source_weights,
        half_life_days=half_life_days,
        default_weight=default_weight,
    )

    velocity_result = calculate_topic_velocity(
        articles,
        now,
        previous_days=previous_days,
    )

    return {
        **article_result,
        **velocity_result,
        "source_count": count_distinct_sources(articles),
        "swedish_signal": calculate_swedish_signal(
            articles,
            swedish_sources,
        ),
    }


def calculate_topic_score(
    metrics,
    *,
    breadth_weight,
    velocity_weight,
    swedish_weight,
):
    weights = (breadth_weight, velocity_weight, swedish_weight)
    if any(weight < 0 for weight in weights):
        raise ValueError("ranking weights must not be negative")

    multiplier = (
        1
        + breadth_weight * metrics["source_count"]
        + velocity_weight * metrics["velocity"]
        + swedish_weight * metrics["swedish_signal"]
    )

    return metrics["article_score"] * multiplier


def build_topic_score_result(
    metrics,
    now,
    *,
    breadth_weight,
    velocity_weight,
    swedish_weight,
    score_version,
):
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must include a timezone")

    if not isinstance(score_version, str) or not score_version.strip():
        raise ValueError("score_version must be a non-empty string")

    score = calculate_topic_score(
        metrics,
        breadth_weight=breadth_weight,
        velocity_weight=velocity_weight,
        swedish_weight=swedish_weight,
    )

    article_score = metrics["article_score"]

    return {
        "score": score,
        "score_calculated_at": now.astimezone(timezone.utc).isoformat(),
        "score_version": score_version,
        "score_breakdown": {
            "metrics": metrics,
            "weights": {
                "breadth": breadth_weight,
                "velocity": velocity_weight,
                "swedish": swedish_weight,
            },
            "contributions": {
                "base": article_score,
                "breadth": (article_score * breadth_weight * metrics["source_count"]),
                "velocity": (article_score * velocity_weight * metrics["velocity"]),
                "swedish": (article_score * swedish_weight * metrics["swedish_signal"]),
            },
        },
    }


def calculate_topic_ranking(
    articles,
    now,
    source_weights,
    swedish_sources,
    *,
    breadth_weight,
    velocity_weight,
    swedish_weight,
    score_version,
    half_life_days=3,
    default_weight=1.0,
    previous_days=7,
):
    metrics = calculate_topic_metrics(
        articles,
        now,
        source_weights,
        swedish_sources,
        half_life_days=half_life_days,
        default_weight=default_weight,
        previous_days=previous_days,
    )

    return build_topic_score_result(
        metrics,
        now,
        breadth_weight=breadth_weight,
        velocity_weight=velocity_weight,
        swedish_weight=swedish_weight,
        score_version=score_version,
    )
