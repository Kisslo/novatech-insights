-- Local test only. All test records are rolled back.
-- ID ordering is for testing, not the final selection rule.
\set ON_ERROR_STOP on

BEGIN;

CREATE TEMP TABLE test_topic_ids (
    id bigint PRIMARY KEY
) ON COMMIT DROP;

WITH new_topic AS (
    INSERT INTO public.topics (label)
    VALUES ('Local article-count test')
    RETURNING id
)
INSERT INTO test_topic_ids (id)
SELECT id FROM new_topic;

WITH new_articles AS (
    INSERT INTO public.news (title, link, source, published)
    VALUES
        ('Test article A', 'https://example.com/count-test-a',
         'Source A', now()),
        ('Test article B', 'https://example.com/count-test-b',
         'Source A', now()),
        ('Test article C', 'https://example.com/count-test-c',
         'Source A', now()),
        ('Test article D', 'https://example.com/count-test-d',
         'Source B', now())
    RETURNING id
)
INSERT INTO public.topic_articles (topic_id, news_id)
SELECT t.id, a.id
FROM test_topic_ids AS t
CROSS JOIN new_articles AS a;

CREATE TEMP TABLE test_display_results ON COMMIT DROP AS
WITH topic_counts AS (
    SELECT
        ta.topic_id,
        count(DISTINCT n.id) AS article_count,
        count(DISTINCT n.source) AS source_count
    FROM public.topic_articles AS ta
    JOIN public.news AS n ON n.id = ta.news_id
    JOIN test_topic_ids AS t ON t.id = ta.topic_id
    GROUP BY ta.topic_id
),
selected_articles AS (
    SELECT
        ta.topic_id,
        n.id AS news_id,
        n.title,
        n.source,
        row_number() OVER (
            PARTITION BY ta.topic_id ORDER BY n.id
        ) AS rank_in_topic
    FROM public.topic_articles AS ta
    JOIN public.news AS n ON n.id = ta.news_id
    JOIN test_topic_ids AS t ON t.id = ta.topic_id
)
SELECT
    a.topic_id,
    a.news_id,
    a.title,
    a.source,
    a.rank_in_topic,
    c.article_count,
    c.source_count
FROM selected_articles AS a
JOIN topic_counts AS c ON c.topic_id = a.topic_id
WHERE a.rank_in_topic <= 3;

DO $test$
BEGIN
    IF (SELECT count(*) FROM test_display_results) <> 3 THEN
        RAISE EXCEPTION 'FAIL: expected 3 displayed articles';
    END IF;

    IF (SELECT count(DISTINCT news_id)
        FROM test_display_results) <> 3 THEN
        RAISE EXCEPTION 'FAIL: displayed articles must be distinct';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM test_display_results
        WHERE article_count IS DISTINCT FROM 4::bigint
           OR source_count IS DISTINCT FROM 2::bigint
    ) THEN
        RAISE EXCEPTION
            'FAIL: full counts must remain 4 articles and 2 sources';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM test_display_results
        WHERE source IS DISTINCT FROM 'Source A'
    ) THEN
        RAISE EXCEPTION
            'FAIL: only Source A articles should be displayed';
    END IF;

    IF (
        SELECT array_agg(rank_in_topic ORDER BY rank_in_topic)
        FROM test_display_results
    ) IS DISTINCT FROM ARRAY[1, 2, 3]::bigint[] THEN
        RAISE EXCEPTION 'FAIL: expected article positions 1, 2 and 3';
    END IF;

    RAISE NOTICE 'PASS: all topic-count assertions passed';
END;
$test$;

SELECT *
FROM test_display_results
ORDER BY topic_id, rank_in_topic;

ROLLBACK;