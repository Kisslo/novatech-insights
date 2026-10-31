-- Local test only. Test rows are rolled back.
\set ON_ERROR_STOP on

BEGIN;

CREATE TEMP TABLE selection_topic (
    id bigint PRIMARY KEY
) ON COMMIT DROP;

CREATE TEMP TABLE selection_articles (
    id bigint PRIMARY KEY,
    link text NOT NULL
) ON COMMIT DROP;

WITH inserted AS (
    INSERT INTO public.topics (label)
    VALUES ('Local article-selection test')
    RETURNING id
)
INSERT INTO selection_topic
SELECT id FROM inserted;

WITH inserted AS (
    INSERT INTO public.news (
        title, link, source, published, description
    )
    VALUES
        (
            'A with description',
            'https://example.com/selection-a-description',
            'Source A', '2026-10-28 12:00:00+00',
            'Useful description'
        ),
        (
            'A newer but empty',
            'https://example.com/selection-a-empty',
            'Source A', '2026-10-31 12:00:00+00', ''
        ),
        (
            'B with description',
            'https://example.com/selection-b-description',
            'Source B', '2026-10-30 12:00:00+00',
            'Useful description'
        ),
        (
            'B newer but whitespace',
            'https://example.com/selection-b-whitespace',
            'Source B', '2026-10-31 12:00:00+00',
            E' \t\n '
        ),
        (
            'C tied article one',
            'https://example.com/selection-c-one',
            'Source C', '2026-10-29 12:00:00+00',
            'Useful description'
        ),
        (
            'C tied article two',
            'https://example.com/selection-c-two',
            'Source C', '2026-10-29 12:00:00+00',
            'Useful description'
        ),
        (
            'D newest but whitespace',
            'https://example.com/selection-d-whitespace',
            'Source D', '2026-10-31 13:00:00+00',
            E' \t\n '
        ),
        (
            'E older with description',
            'https://example.com/selection-e-description',
            'Source E', '2026-10-27 12:00:00+00',
            'Useful description'
        )
    RETURNING id, link
)
INSERT INTO selection_articles
SELECT id, link FROM inserted;

INSERT INTO public.topic_articles (topic_id, news_id)
SELECT t.id, a.id
FROM selection_topic AS t
CROSS JOIN selection_articles AS a;

CREATE TEMP TABLE selection_results ON COMMIT DROP AS
SELECT a.*
FROM public.topic_top_articles AS a
JOIN selection_topic AS t ON t.id = a.topic_id;

DO $test$
DECLARE
    expected_ids bigint[];
    actual_ids bigint[];
BEGIN
    expected_ids := ARRAY[
        (
            SELECT id FROM selection_articles
            WHERE link = 'https://example.com/selection-b-description'
        ),
        (
            SELECT min(id) FROM selection_articles
            WHERE link IN (
                'https://example.com/selection-c-one',
                'https://example.com/selection-c-two'
            )
        ),
        (
            SELECT id FROM selection_articles
            WHERE link = 'https://example.com/selection-a-description'
        )
    ];

    SELECT array_agg(news_id ORDER BY rank_in_topic)
    INTO actual_ids
    FROM selection_results;

    IF actual_ids IS DISTINCT FROM expected_ids THEN
        RAISE EXCEPTION
            'FAIL: expected article IDs %, got %',
            expected_ids, actual_ids;
    END IF;

    IF (SELECT count(*) FROM selection_results) <> 3 THEN
        RAISE EXCEPTION 'FAIL: expected exactly 3 articles';
    END IF;

    IF (SELECT count(DISTINCT source)
        FROM selection_results) <> 3 THEN
        RAISE EXCEPTION 'FAIL: expected 3 different sources';
    END IF;

    IF (
        SELECT array_agg(rank_in_topic ORDER BY rank_in_topic)
        FROM selection_results
    ) IS DISTINCT FROM ARRAY[1, 2, 3]::bigint[] THEN
        RAISE EXCEPTION 'FAIL: expected ranks 1, 2 and 3';
    END IF;

    IF (
        SELECT count(*)
        FROM public.topic_overview AS o
        JOIN selection_topic AS t ON t.id = o.id
        WHERE o.article_count = 8
          AND o.source_count = 5
    ) <> 1 THEN
        RAISE EXCEPTION
            'FAIL: full counts must remain 8 articles and 5 sources';
    END IF;

    RAISE NOTICE 'PASS: all article-selection assertions passed';
END;
$test$;

SELECT *
FROM selection_results
ORDER BY rank_in_topic;

ROLLBACK;