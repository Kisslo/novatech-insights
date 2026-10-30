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
