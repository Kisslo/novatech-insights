def count_distinct_sources(articles):
    sources = set()

    for article in articles:
        source = article.get("source")
        if source:
            sources.add(source)

    return len(sources)
