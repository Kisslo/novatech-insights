-- Draft migration for issue #26.
-- Local testing only until reviewed.
-- Whitespace-only descriptions are treated as empty.
-- Source comparisons ignore case and surrounding ASCII whitespace.
-- Full alignment with Python Unicode casefold/strip remains pending.
-- Backend grants are applied separately by migration 006.

BEGIN;

CREATE OR REPLACE VIEW public.topic_overview
WITH (security_invoker = true)
AS
SELECT
    t.id,
    t.label,
    t.why_relevant_sv,
    t.llm_relevance,
    t.score,
    COUNT(n.id) AS article_count,
    COUNT(
        DISTINCT NULLIF(
            lower(btrim(n.source, E' \t\n\r\f\013')),
            ''
        )
    ) AS source_count
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

CREATE OR REPLACE VIEW public.topic_top_articles
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
            PARTITION BY
                topic_id,
                NULLIF(
                    lower(btrim(source, E' \t\n\r\f\013')),
                    ''
                )
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

-- Remove automatic grants when Supabase roles exist.
-- Reapply migration 006 after rerunning this migration locally.

DO $permissions$
DECLARE
    role_name text;
BEGIN
    FOR role_name IN
        SELECT rolname
        FROM pg_roles
        WHERE rolname IN ('anon', 'authenticated', 'service_role')
    LOOP
        EXECUTE format(
            'REVOKE ALL ON TABLE public.topic_overview, public.topic_top_articles FROM %I',
            role_name
        );
    END LOOP;
END;
$permissions$;

COMMENT ON VIEW public.topic_overview IS
'Topic details and counts across all linked articles.
Includes empty topics; the reader filters before limiting results.
Source counts ignore case and surrounding ASCII whitespace.
NULL and blank source names are excluded from source counts.';

COMMENT ON VIEW public.topic_top_articles IS
'Up to three articles per topic, at most one per normalized source.
Source comparisons ignore case and surrounding ASCII whitespace.
NULL and blank sources share one selection bucket.
Original source names are preserved for display.
Prefer descriptions, then newer dates, then smaller news IDs.
Readers must order by topic_id and rank_in_topic.';

COMMIT;