-- Local and CI test only. Test records are rolled back.
\set ON_ERROR_STOP on

BEGIN;

DO $test$
DECLARE
    article_id bigint;
    first_topic_id bigint;
    second_topic_id bigint;
    missing_article_id bigint;
    missing_topic_id bigint;
    link_count bigint;
BEGIN
    INSERT INTO public.news (title, link, source, published)
    VALUES (
        'Relationship test article',
        'https://example.com/constraint-test-article',
        'Test source',
        now()
    )
    RETURNING id INTO article_id;

    INSERT INTO public.topics (label)
    VALUES ('Relationship test topic A')
    RETURNING id INTO first_topic_id;

    INSERT INTO public.topics (label)
    VALUES ('Relationship test topic B')
    RETURNING id INTO second_topic_id;

    -- One article can belong to two different topics.
    INSERT INTO public.topic_articles (topic_id, news_id)
    VALUES
        (first_topic_id, article_id),
        (second_topic_id, article_id);

    SELECT count(*)
    INTO link_count
    FROM public.topic_articles
    WHERE news_id = article_id;

    IF link_count <> 2 THEN
        RAISE EXCEPTION 'FAIL: expected two topic memberships';
    END IF;

    -- The same article-topic pair cannot be inserted twice.
    BEGIN
        INSERT INTO public.topic_articles (topic_id, news_id)
        VALUES (first_topic_id, article_id);

        RAISE EXCEPTION 'FAIL: duplicate membership was accepted';
    EXCEPTION
        WHEN unique_violation THEN
            NULL; -- Expected rejection.
    END;

    -- Create and remove a temporary article to obtain a missing ID.
    INSERT INTO public.news (title, link, source, published)
    VALUES (
        'Temporary missing-article fixture',
        'https://example.com/constraint-test-missing-article',
        'Test source',
        now()
    )
    RETURNING id INTO missing_article_id;

    DELETE FROM public.news
    WHERE id = missing_article_id;

    BEGIN
        INSERT INTO public.topic_articles (topic_id, news_id)
        VALUES (first_topic_id, missing_article_id);

        RAISE EXCEPTION 'FAIL: missing article reference was accepted';
    EXCEPTION
        WHEN foreign_key_violation THEN
            NULL; -- Expected rejection.
    END;

    -- Create and remove a temporary topic to obtain a missing ID.
    INSERT INTO public.topics (label)
    VALUES ('Temporary missing-topic fixture')
    RETURNING id INTO missing_topic_id;

    DELETE FROM public.topics
    WHERE id = missing_topic_id;

    BEGIN
        INSERT INTO public.topic_articles (topic_id, news_id)
        VALUES (missing_topic_id, article_id);

        RAISE EXCEPTION 'FAIL: missing topic reference was accepted';
    EXCEPTION
        WHEN foreign_key_violation THEN
            NULL; -- Expected rejection.
    END;
    -- An article with topic memberships cannot be deleted.
    BEGIN
        DELETE FROM public.news
        WHERE id = article_id;

        RAISE EXCEPTION 'FAIL: linked article deletion was accepted';
    EXCEPTION
        WHEN foreign_key_violation THEN
            NULL; -- Expected rejection.
    END;

    -- A topic with article memberships cannot be deleted.
    BEGIN
        DELETE FROM public.topics
        WHERE id = first_topic_id;

        RAISE EXCEPTION 'FAIL: linked topic deletion was accepted';
    EXCEPTION
        WHEN foreign_key_violation THEN
            NULL; -- Expected rejection.
    END;

    -- Both parent records must still exist.
    IF NOT EXISTS (
        SELECT 1 FROM public.news WHERE id = article_id
    ) THEN
        RAISE EXCEPTION 'FAIL: linked article was not preserved';
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM public.topics WHERE id = first_topic_id
    ) THEN
        RAISE EXCEPTION 'FAIL: linked topic was not preserved';
    END IF;
    -- Failed inserts and deletes must not change the valid memberships.
    SELECT count(*)
    INTO link_count
    FROM public.topic_articles
    WHERE news_id = article_id;

    IF link_count <> 2 THEN
        RAISE EXCEPTION 'FAIL: valid memberships changed';
    END IF;

    RAISE NOTICE 'PASS: all topic relationship assertions passed';
END;
$test$;

ROLLBACK;