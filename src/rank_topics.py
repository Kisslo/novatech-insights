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
