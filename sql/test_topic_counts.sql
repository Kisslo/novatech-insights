-- Local test only. Test rows are rolled back.
-- Checks the actual views and full-topic counts.
\set ON_ERROR_STOP on

BEGIN;

CREATE TEMP TABLE test_topic_ids (
    id bigint PRIMARY KEY,
    is_empty boolean NOT NULL
) ON COMMIT DROP;

WITH new_topic AS (
    INSERT INTO public.topics (label)
    VALUES ('Local article-count test')
    RETURNING id
)
INSERT INTO test_topic_ids (id, is_empty)
SELECT id, false FROM new_topic;

WITH new_topic AS (
    INSERT INTO public.topics (label)
    VALUES ('Local empty-topic test')
    RETURNING id
)
INSERT INTO test_topic_ids (id, is_empty)
SELECT id, true FROM new_topic;

WITH new_articles AS (
    INSERT INTO public.news (title, link, source, published)
    VALUES
        ('Test article A', 'https://example.com/count-test-a',
         'Source A', '2026-10-28 12:00:00+00'),
        ('Test article B', 'https://example.com/count-test-b',
         'Source A', '2026-10-29 12:00:00+00'),
        ('Test article C', 'https://example.com/count-test-c',
         'Source A', '2026-10-30 12:00:00+00'),
        ('Test article D', 'https://example.com/count-test-d',
         'Source B', '2026-10-30 13:00:00+00')
    RETURNING id
)
INSERT INTO public.topic_articles (topic_id, news_id)
SELECT t.id, a.id
FROM test_topic_ids AS t
CROSS JOIN new_articles AS a
WHERE NOT t.is_empty;

CREATE TEMP TABLE test_display_results ON COMMIT DROP AS
SELECT
    a.topic_id,
    a.news_id,
    a.title,
    a.source,
    a.rank_in_topic,
    o.article_count,
    o.source_count
FROM public.topic_top_articles AS a
JOIN public.topic_overview AS o
    ON o.id = a.topic_id
JOIN test_topic_ids AS t
    ON t.id = a.topic_id
WHERE NOT t.is_empty;

DO $test$
BEGIN
    IF (SELECT count(*) FROM test_display_results) <> 2 THEN
        RAISE EXCEPTION 'FAIL: expected 2 displayed articles';
    END IF;

    IF (SELECT count(DISTINCT news_id)
        FROM test_display_results) <> 2 THEN
        RAISE EXCEPTION 'FAIL: displayed articles must be distinct';
    END IF;

    IF (SELECT count(DISTINCT source)
        FROM test_display_results) <> 2 THEN
        RAISE EXCEPTION 'FAIL: expected 2 different sources';
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

    IF (
        SELECT array_agg(title ORDER BY rank_in_topic)
        FROM test_display_results
    ) IS DISTINCT FROM ARRAY[
        'Test article D', 'Test article C'
    ]::text[] THEN
        RAISE EXCEPTION
            'FAIL: expected newest Source B article, then newest Source A article';
    END IF;

    IF (
        SELECT array_agg(rank_in_topic ORDER BY rank_in_topic)
        FROM test_display_results
    ) IS DISTINCT FROM ARRAY[1, 2]::bigint[] THEN
        RAISE EXCEPTION 'FAIL: expected article positions 1 and 2';
    END IF;

    IF (
        SELECT count(*)
        FROM public.topic_overview AS o
        JOIN test_topic_ids AS t ON t.id = o.id
        WHERE t.is_empty
          AND o.article_count = 0
          AND o.source_count = 0
    ) <> 1 THEN
        RAISE EXCEPTION
            'FAIL: empty topic must appear with zero counts';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM public.topic_top_articles AS a
        JOIN test_topic_ids AS t ON t.id = a.topic_id
        WHERE t.is_empty
    ) THEN
        RAISE EXCEPTION
            'FAIL: empty topic must have no selected articles';
    END IF;

    RAISE NOTICE 'PASS: all topic-count assertions passed';
END;
$test$;

SELECT *
FROM test_display_results
ORDER BY topic_id, rank_in_topic;

ROLLBACK;