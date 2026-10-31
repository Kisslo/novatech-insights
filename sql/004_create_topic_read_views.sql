-- Draft migration for issue #26.
-- Local testing only until reviewed.
-- Whitespace-only descriptions are treated as empty.
-- Sources are compared using their stored values.
-- Backend grants and permission tests remain pending.

BEGIN;

CREATE VIEW public.topic_overview
WITH (security_invoker = true)
AS
SELECT
    t.id,
    t.label,
    t.why_relevant_sv,
    t.llm_relevance,
    t.score,
    COUNT(n.id) AS article_count,
    COUNT(DISTINCT n.source) AS source_count
FROM public.topics AS t
LEFT JOIN public.topic_articles AS ta
    ON ta.topic_id = t.id
LEFT JOIN public.news AS n
    ON n.id = ta.news_id
GROUP BY
    t.id,
    t.label,
    t.why_relevant_sv,
    t.llm_relevance,
    t.score;

CREATE VIEW public.topic_top_articles
WITH (security_invoker = true)
AS
WITH candidates AS (
    SELECT
        ta.topic_id,
        n.id AS news_id,
        n.title,
        n.source,
        n.link,
        n.description,
        n.published,
        COALESCE(
            n.description ~ '[^[:space:]]',
            false
        ) AS has_description
    FROM public.topic_articles AS ta
    JOIN public.news AS n
        ON n.id = ta.news_id
),
ranked_per_source AS (
    SELECT
        candidates.*,
        ROW_NUMBER() OVER (
            PARTITION BY topic_id, source
            ORDER BY
                has_description DESC,
                published DESC NULLS LAST,
                news_id ASC
        ) AS source_rank
    FROM candidates
),
ranked_per_topic AS (
    SELECT
        topic_id,
        news_id,
        title,
        source,
        link,
        description,
        ROW_NUMBER() OVER (
            PARTITION BY topic_id
            ORDER BY
                has_description DESC,
                published DESC NULLS LAST,
                news_id ASC
        ) AS rank_in_topic
    FROM ranked_per_source
    WHERE source_rank = 1
)
SELECT
    topic_id,
    rank_in_topic,
    news_id,
    title,
    source,
    link,
    description
FROM ranked_per_topic
WHERE rank_in_topic <= 3;

REVOKE ALL ON TABLE public.topic_overview FROM PUBLIC;
REVOKE ALL ON TABLE public.topic_top_articles FROM PUBLIC;

COMMENT ON VIEW public.topic_overview IS
'Topic details and counts across all linked articles.
Includes empty topics; the reader filters before limiting results.';

COMMENT ON VIEW public.topic_top_articles IS
'Up to three articles per topic, at most one per stored source.
Prefer descriptions, then newer dates, then smaller news IDs.
Readers must order by topic_id and rank_in_topic.';

COMMIT;