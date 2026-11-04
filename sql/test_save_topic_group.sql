-- Local test only. All test data is rolled back.
\set ON_ERROR_STOP on

BEGIN;

DO $test$
DECLARE
    article_ids bigint[];
    first_topic_id bigint;
    repeated_topic_id bigint;
    missing_news_id bigint;
    topics_before bigint;
    links_before bigint;
    rejected boolean := false;
BEGIN
    WITH inserted AS (
        INSERT INTO public.news (title, link, source, published)
        VALUES
            (
                'Save-group test A',
                'https://example.com/save-group-test-a',
                'Source A',
                now()
            ),
            (
                'Save-group test B',
                'https://example.com/save-group-test-b',
                'Source B',
                now()
            )
        RETURNING id
    )
    SELECT array_agg(id ORDER BY id)
    INTO article_ids
    FROM inserted;

    first_topic_id := public.save_topic_group(article_ids);

    IF NOT EXISTS (
        SELECT 1 FROM public.topics WHERE id = first_topic_id
    ) THEN
        RAISE EXCEPTION 'FAIL: topic was not created';
    END IF;

    IF (
        SELECT array_agg(news_id ORDER BY news_id)
        FROM public.topic_articles
        WHERE topic_id = first_topic_id
    ) IS DISTINCT FROM article_ids THEN
        RAISE EXCEPTION 'FAIL: article links do not match';
    END IF;

    RAISE NOTICE 'PASS: topic and all article links saved';

    -- Simulate labels and scores added by downstream steps.
    UPDATE public.topics
    SET label = 'Keep this label',
        score = 0.75,
        score_calculated_at = now(),
        score_version = 'test-v1',
        score_breakdown = '{"test": true}'::jsonb
    WHERE id = first_topic_id;

    SELECT count(*) INTO topics_before FROM public.topics;
    SELECT count(*) INTO links_before FROM public.topic_articles;

    -- Reordered and repeated IDs must reuse the same topic.
    repeated_topic_id := public.save_topic_group(
        ARRAY[article_ids[2], article_ids[1], article_ids[1]]
    );

    IF repeated_topic_id IS DISTINCT FROM first_topic_id THEN
        RAISE EXCEPTION 'FAIL: repeated save returned a different topic';
    END IF;

    IF (SELECT count(*) FROM public.topics) <> topics_before
       OR (SELECT count(*) FROM public.topic_articles) <> links_before THEN
        RAISE EXCEPTION 'FAIL: repeated save created extra rows';
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM public.topics
        WHERE id = first_topic_id
          AND label = 'Keep this label'
          AND score = 0.75
          AND score_calculated_at = now()
          AND score_version = 'test-v1'
          AND score_breakdown = '{"test": true}'::jsonb
    ) THEN
        RAISE EXCEPTION 'FAIL: existing label or score was changed';
    END IF;

    RAISE NOTICE 'PASS: repeated save reuses topic and preserves metadata';

    -- Create and remove an unlinked article to obtain a missing ID.
    INSERT INTO public.news (title, link, source, published)
    VALUES (
        'Temporary missing article',
        'https://example.com/save-group-test-missing',
        'Source C',
        now()
    )
    RETURNING id INTO missing_news_id;

    DELETE FROM public.news WHERE id = missing_news_id;

    BEGIN
        PERFORM public.save_topic_group(
            ARRAY[article_ids[1], missing_news_id]
        );
    EXCEPTION
        WHEN foreign_key_violation THEN
            rejected := true;
    END;

    IF NOT rejected THEN
        RAISE EXCEPTION 'FAIL: missing article ID was accepted';
    END IF;

    IF (SELECT count(*) FROM public.topics) <> topics_before
       OR (SELECT count(*) FROM public.topic_articles) <> links_before THEN
        RAISE EXCEPTION 'FAIL: failed save left partial data';
    END IF;

    RAISE NOTICE 'PASS: failed save leaves no partial topic or links';
END;
$test$;

ROLLBACK;