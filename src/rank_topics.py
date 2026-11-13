import logging
from datetime import datetime, timedelta, timezone


def parse_publication_time(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("published must be a non-empty ISO timestamp")
    published = datetime.fromisoformat(value.strip())
    if published.tzinfo is None:
        raise ValueError("published must include a timezone")
    return published.astimezone(timezone.utc)


FUTURE_TOLERANCE = timedelta(minutes=5)


class InvalidPublicationTimeError(ValueError):
    """An article has a missing, invalid or excessive future timestamp."""


def get_effective_publication_time(value, now):
    """Clamp tolerated future timestamps to now without changing metadata."""
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must include a timezone")
    try:
        published = parse_publication_time(value)
    except ValueError as error:
        raise InvalidPublicationTimeError(str(error)) from error
    if published > now + FUTURE_TOLERANCE:
        raise InvalidPublicationTimeError(
            "published exceeds the five-minute future tolerance"
        )
    return min(published, now)


def count_distinct_sources(articles):
    sources = set()
    for article in articles:
        source = article.get("source")
        if source:
            sources.add(source)
    return len(sources)


def calculate_weighted_source_breadth(articles, now, half_life_days=3):
    """Weight each distinct source by its freshest article's time decay."""
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must include a timezone")
    if half_life_days <= 0:
        raise ValueError("half_life_days must be greater than zero")
    latest_weight_by_source = {}
    for article in articles:
        source = article.get("source")
        if not source:
            continue
        published = get_effective_publication_time(article.get("published"), now)
        age_days = (now - published).total_seconds() / 86400
        weight = calculate_time_decay(age_days, half_life_days)
        latest_weight_by_source[source] = max(
            latest_weight_by_source.get(source, 0.0), weight
        )
    return sum(latest_weight_by_source.values())


def calculate_time_decay(age_days, half_life_days):
    if half_life_days <= 0:
        raise ValueError("half_life_days must be greater than zero")
    if age_days < 0:
        raise ValueError("age_days must not be negative")
    return 0.5 ** (age_days / half_life_days)


def calculate_velocity(recent_count, previous_count, previous_days=6):
    if recent_count < 0 or previous_count < 0:
        raise ValueError("article counts must not be negative")
    if previous_days <= 0:
        raise ValueError("previous_days must be greater than zero")
    daily_average = previous_count / previous_days
    return recent_count / max(daily_average, 1)


def count_velocity_articles(articles, now, previous_days=6):
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
        published = get_effective_publication_time(article.get("published"), now)
        if recent_start < published <= now:
            recent_count += 1
        elif previous_start < published <= recent_start:
            previous_count += 1
    return (recent_count, previous_count)


def calculate_topic_velocity(articles, now, previous_days=6):
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
    *,
    authority_base_factor=1.5,
    authority_total_start_factor=10.0,
    authority_bonus_half_life_days=0.7,
):
    if authority_base_factor < 0 or authority_total_start_factor < 0:
        raise ValueError("authority factors must not be negative")
    if authority_base_factor > authority_total_start_factor:
        raise ValueError(
            "authority_base_factor must not exceed authority_total_start_factor"
        )
    if authority_bonus_half_life_days <= 0:
        raise ValueError("authority_bonus_half_life_days must be greater than zero")
    published = get_effective_publication_time(article.get("published"), now)
    age_days = (now - published).total_seconds() / 86400
    source_weight = get_source_weight(
        article.get("source"), source_weights, default_weight
    )
    time_weight = calculate_time_decay(age_days, half_life_days)
    source_type = article.get("source_type")
    authority_bonus_decay = 0.0
    authority_bonus = 0.0
    authority_base_weight = source_weight
    if source_type == "authority":
        authority_base_weight = source_weight * authority_base_factor
        authority_bonus_decay = calculate_time_decay(
            age_days, authority_bonus_half_life_days
        )
        authority_bonus = (
            source_weight
            * (authority_total_start_factor - authority_base_factor)
            * authority_bonus_decay
        )
    contribution = (authority_base_weight + authority_bonus) * time_weight
    return {
        "source_weight": source_weight,
        "time_weight": time_weight,
        "source_type": source_type,
        "authority_base_weight": authority_base_weight,
        "authority_bonus": authority_bonus,
        "authority_bonus_time_weight": authority_bonus_decay,
        "contribution": contribution,
    }


def calculate_topic_article_score(
    articles,
    now,
    source_weights,
    half_life_days=3,
    default_weight=1.0,
    *,
    authority_base_factor=1.5,
    authority_total_start_factor=10.0,
    authority_bonus_half_life_days=0.7,
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
            authority_base_factor=authority_base_factor,
            authority_total_start_factor=authority_total_start_factor,
            authority_bonus_half_life_days=authority_bonus_half_life_days,
        )
        contributions.append({"news_id": article_id, **result})
    return {
        "article_score": sum((item["contribution"] for item in contributions)),
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
    previous_days=6,
    *,
    authority_base_factor=1.5,
    authority_total_start_factor=10.0,
    authority_bonus_half_life_days=0.7,
):
    unique_articles = {}
    for article in articles:
        article_id = article["id"]
        if article_id not in unique_articles:
            unique_articles[article_id] = article
    articles = list(unique_articles.values())
    swedish_sources = tuple(swedish_sources)
    swedish_article_ids = {
        article["id"]
        for article in articles
        if calculate_swedish_signal([article], swedish_sources)
    }
    article_result = calculate_topic_article_score(
        articles,
        now,
        source_weights,
        half_life_days=half_life_days,
        default_weight=default_weight,
        authority_base_factor=authority_base_factor,
        authority_total_start_factor=authority_total_start_factor,
        authority_bonus_half_life_days=authority_bonus_half_life_days,
    )
    swedish_article_score = sum(
        (
            item["contribution"]
            for item in article_result["contributions"]
            if item["news_id"] in swedish_article_ids
        )
    )
    velocity_result = calculate_topic_velocity(
        articles, now, previous_days=previous_days
    )
    return {
        **article_result,
        **velocity_result,
        "swedish_article_score": swedish_article_score,
        "source_count": count_distinct_sources(articles),
        "source_breadth": calculate_weighted_source_breadth(
            articles, now, half_life_days=half_life_days
        ),
        "swedish_signal": calculate_swedish_signal(articles, swedish_sources),
        "authority_article_score": sum(
            item["contribution"]
            for item in article_result["contributions"]
            if item["source_type"] == "authority"
        ),
        "authority_base_score": sum(
            item["authority_base_weight"] * item["time_weight"]
            for item in article_result["contributions"]
            if item["source_type"] == "authority"
        ),
        "authority_base_factor": authority_base_factor,
        "authority_total_start_factor": authority_total_start_factor,
        "authority_bonus_half_life_days": authority_bonus_half_life_days,
        "authority_bonus_score": sum(
            item["authority_bonus"] * item["time_weight"]
            for item in article_result["contributions"]
            if item["source_type"] == "authority"
        ),
    }


def calculate_saturating_bonus(value, max_bonus, scale):
    """Return a smoothly increasing bonus bounded by max_bonus."""
    if value < 0:
        raise ValueError("value must not be negative")
    if max_bonus < 0:
        raise ValueError("max_bonus must not be negative")
    if scale <= 0:
        raise ValueError("scale must be greater than zero")
    return max_bonus * (value / (scale + value))


def calculate_topic_score_contributions(
    metrics,
    *,
    max_breadth_bonus=1.0,
    breadth_scale=3.0,
    max_velocity_bonus=1.0,
    velocity_scale=5.0,
    swedish_weight=0.5,
):
    """Calculate score contributions using bounded bonus factors."""
    if swedish_weight < 0:
        raise ValueError("swedish_weight must not be negative")
    breadth_bonus = calculate_saturating_bonus(
        metrics["source_breadth"], max_breadth_bonus, breadth_scale
    )
    velocity_bonus = calculate_saturating_bonus(
        metrics["velocity"], max_velocity_bonus, velocity_scale
    )
    article_score = metrics["article_score"]
    return {
        "base": article_score,
        "breadth": article_score * breadth_bonus,
        "velocity": article_score * velocity_bonus,
        "swedish": swedish_weight * metrics["swedish_article_score"],
    }


def calculate_topic_score(
    metrics,
    *,
    max_breadth_bonus=1.0,
    breadth_scale=3.0,
    max_velocity_bonus=1.0,
    velocity_scale=5.0,
    swedish_weight=0.5,
):
    contributions = calculate_topic_score_contributions(
        metrics,
        max_breadth_bonus=max_breadth_bonus,
        breadth_scale=breadth_scale,
        max_velocity_bonus=max_velocity_bonus,
        velocity_scale=velocity_scale,
        swedish_weight=swedish_weight,
    )
    return sum(contributions.values())


def build_topic_score_result(
    metrics,
    now,
    *,
    max_breadth_bonus=1.0,
    breadth_scale=3.0,
    max_velocity_bonus=1.0,
    velocity_scale=5.0,
    swedish_weight=0.5,
    score_version="preliminary-v2",
):
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must include a timezone")
    if not isinstance(score_version, str) or not score_version.strip():
        raise ValueError("score_version must be a non-empty string")
    contributions = calculate_topic_score_contributions(
        metrics,
        max_breadth_bonus=max_breadth_bonus,
        breadth_scale=breadth_scale,
        max_velocity_bonus=max_velocity_bonus,
        velocity_scale=velocity_scale,
        swedish_weight=swedish_weight,
    )
    return {
        "score": sum(contributions.values()),
        "score_calculated_at": now.astimezone(timezone.utc).isoformat(),
        "score_version": score_version,
        "score_breakdown": {
            "metrics": metrics,
            "weights": {
                "max_breadth_bonus": max_breadth_bonus,
                "breadth_scale": breadth_scale,
                "max_velocity_bonus": max_velocity_bonus,
                "velocity_scale": velocity_scale,
                "swedish": swedish_weight,
            },
            "contributions": contributions,
        },
    }


def calculate_topic_ranking(
    articles,
    now,
    source_weights,
    swedish_sources,
    *,
    max_breadth_bonus=1.0,
    breadth_scale=3.0,
    max_velocity_bonus=1.0,
    velocity_scale=5.0,
    swedish_weight=0.5,
    score_version="preliminary-v2",
    half_life_days=3,
    default_weight=1.0,
    previous_days=6,
    authority_base_factor=1.5,
    authority_total_start_factor=10.0,
    authority_bonus_half_life_days=0.7,
):
    metrics = calculate_topic_metrics(
        articles,
        now,
        source_weights,
        swedish_sources,
        half_life_days=half_life_days,
        default_weight=default_weight,
        previous_days=previous_days,
        authority_base_factor=authority_base_factor,
        authority_total_start_factor=authority_total_start_factor,
        authority_bonus_half_life_days=authority_bonus_half_life_days,
    )
    result = build_topic_score_result(
        metrics,
        now,
        max_breadth_bonus=max_breadth_bonus,
        breadth_scale=breadth_scale,
        max_velocity_bonus=max_velocity_bonus,
        velocity_scale=velocity_scale,
        swedish_weight=swedish_weight,
        score_version=score_version,
    )
    result["score_breakdown"]["config"] = {
        "half_life_days": half_life_days,
        "default_source_weight": default_weight,
        "previous_days": previous_days,
        "authority_base_factor": authority_base_factor,
        "authority_total_start_factor": authority_total_start_factor,
        "authority_bonus_half_life_days": authority_bonus_half_life_days,
        "future_tolerance_seconds": FUTURE_TOLERANCE.total_seconds(),
        "source_weights": dict(source_weights),
        "swedish_sources": sorted(swedish_sources),
    }
    return result


def rank_topics(
    topics,
    now,
    source_weights,
    swedish_sources,
    *,
    max_breadth_bonus=1.0,
    breadth_scale=3.0,
    max_velocity_bonus=1.0,
    velocity_scale=5.0,
    swedish_weight=0.5,
    score_version="preliminary-v2",
    half_life_days=3,
    default_weight=1.0,
    previous_days=6,
    top_n=None,
    authority_base_factor=1.5,
    authority_total_start_factor=10.0,
    authority_bonus_half_life_days=0.7,
):
    if top_n is not None:
        if isinstance(top_n, bool) or not isinstance(top_n, int) or top_n < 1:
            raise ValueError("top_n must be a positive integer or None")
    source_weights = dict(source_weights)
    swedish_sources = tuple(swedish_sources)
    ranked = []
    seen_topic_ids = set()
    for topic in topics:
        topic_id = topic["id"]
        if isinstance(topic_id, bool) or not isinstance(topic_id, int):
            raise ValueError("topic id must be an integer")
        if topic_id in seen_topic_ids:
            raise ValueError("topic ids must be unique")
        seen_topic_ids.add(topic_id)
        articles = []
        seen_article_ids = set()
        for article in topic["articles"]:
            article_id = article["id"]
            if article_id in seen_article_ids:
                continue
            seen_article_ids.add(article_id)
            try:
                get_effective_publication_time(article.get("published"), now)
            except InvalidPublicationTimeError as error:
                logging.getLogger(__name__).warning(
                    "Skipping article news_id=%s in topic_id=%s: %s",
                    article_id,
                    topic_id,
                    error,
                )
                continue
            articles.append(article)
        if not articles:
            logging.getLogger(__name__).warning(
                "Skipping topic_id=%s: no valid articles", topic_id
            )
            continue
        result = calculate_topic_ranking(
            articles,
            now,
            source_weights,
            swedish_sources,
            max_breadth_bonus=max_breadth_bonus,
            breadth_scale=breadth_scale,
            max_velocity_bonus=max_velocity_bonus,
            velocity_scale=velocity_scale,
            swedish_weight=swedish_weight,
            score_version=score_version,
            half_life_days=half_life_days,
            default_weight=default_weight,
            previous_days=previous_days,
            authority_base_factor=authority_base_factor,
            authority_total_start_factor=authority_total_start_factor,
            authority_bonus_half_life_days=authority_bonus_half_life_days,
        )
        ranked.append({"id": topic_id, **result})
    ranked.sort(key=lambda topic: (-topic["score"], topic["id"]))
    if top_n is not None:
        return ranked[:top_n]
    return ranked
