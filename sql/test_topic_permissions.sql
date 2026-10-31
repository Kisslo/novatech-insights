-- Local/CI test only. Run as postgres in the test database.
-- Roles, policies, grants and test rows are rolled back.
\set ON_ERROR_STOP on

BEGIN;

CREATE ROLE topic_test_denied
    NOLOGIN NOSUPERUSER NOBYPASSRLS NOINHERIT;

CREATE ROLE topic_test_reader
    NOLOGIN NOSUPERUSER NOBYPASSRLS NOINHERIT;

GRANT USAGE ON SCHEMA public
TO topic_test_denied, topic_test_reader;

-- Create one visible topic and one hidden topic.
-- The visible topic has one visible and one hidden article.
DO $setup$
DECLARE
    visible_topic bigint;
    hidden_topic bigint;
    visible_article bigint;
    hidden_article bigint;
BEGIN
    INSERT INTO public.topics (label)
    VALUES ('Permission test visible topic')
    RETURNING id INTO visible_topic;

    INSERT INTO public.topics (label)
    VALUES ('Permission test hidden topic')
    RETURNING id INTO hidden_topic;

    INSERT INTO public.news (
        title, link, source, published, description
    )
    VALUES (
        'Permission test visible article',
        'https://example.com/permission-visible',
        'Permission Source A',
        '2026-10-30 12:00:00+00',
        'Visible description'
    )
    RETURNING id INTO visible_article;

    INSERT INTO public.news (
        title, link, source, published, description
    )
    VALUES (
        'Permission test hidden article',
        'https://example.com/permission-hidden',
        'Permission Source B',
        '2026-10-30 13:00:00+00',
        'Hidden description'
    )
    RETURNING id INTO hidden_article;

    INSERT INTO public.topic_articles (topic_id, news_id)
    VALUES
        (visible_topic, visible_article),
        (visible_topic, hidden_article),
        (hidden_topic, visible_article);
END;
$setup$;

-- First check: no view permission means access is denied.
SET LOCAL ROLE topic_test_denied;

DO $test$
BEGIN
    BEGIN
        PERFORM 1 FROM public.topic_overview;
        RAISE EXCEPTION 'FAIL: overview access should be denied';
    EXCEPTION
        WHEN insufficient_privilege THEN
            NULL;
    END;

    BEGIN
        PERFORM 1 FROM public.topic_top_articles;
        RAISE EXCEPTION 'FAIL: article view access should be denied';
    EXCEPTION
        WHEN insufficient_privilege THEN
            NULL;
    END;

    RAISE NOTICE 'PASS: role without grants cannot read views';
END;
$test$;

RESET ROLE;

-- Second check: view access alone must not bypass table permissions.
GRANT SELECT ON
    public.topic_overview,
    public.topic_top_articles
TO topic_test_denied;

SET LOCAL ROLE topic_test_denied;

DO $test$
BEGIN
    BEGIN
        PERFORM 1 FROM public.topic_overview;
        RAISE EXCEPTION
            'FAIL: overview must require underlying table permissions';
    EXCEPTION
        WHEN insufficient_privilege THEN
            NULL;
    END;

    BEGIN
        PERFORM 1 FROM public.topic_top_articles;
        RAISE EXCEPTION
            'FAIL: article view must require underlying table permissions';
    EXCEPTION
        WHEN insufficient_privilege THEN
            NULL;
    END;

    RAISE NOTICE 'PASS: view grants alone do not grant table access';
END;
$test$;

RESET ROLE;

-- Reader has SELECT grants but initially no row-security policies.
GRANT SELECT ON
    public.news,
    public.topics,
    public.topic_articles,
    public.topic_overview,
    public.topic_top_articles
TO topic_test_reader;

SET LOCAL ROLE topic_test_reader;

DO $test$
BEGIN
    IF EXISTS (SELECT 1 FROM public.topic_overview)
       OR EXISTS (SELECT 1 FROM public.topic_top_articles) THEN
        RAISE EXCEPTION
            'FAIL: reader without RLS policies must see no rows';
    END IF;

    RAISE NOTICE 'PASS: RLS denies rows without a matching policy';
END;
$test$;

RESET ROLE;

-- Test-only policies allow a restricted subset of the fixture.
CREATE POLICY topic_test_topics_select
ON public.topics
FOR SELECT TO topic_test_reader
USING (label = 'Permission test visible topic');

CREATE POLICY topic_test_news_select
ON public.news
FOR SELECT TO topic_test_reader
USING (link = 'https://example.com/permission-visible');

CREATE POLICY topic_test_memberships_select
ON public.topic_articles
FOR SELECT TO topic_test_reader
USING (
    topic_id IN (
        SELECT id FROM public.topics
        WHERE label = 'Permission test visible topic'
    )
);

SET LOCAL ROLE topic_test_reader;

DO $test$
BEGIN
    IF (SELECT count(*) FROM public.topic_overview) <> 1 THEN
        RAISE EXCEPTION 'FAIL: reader must see exactly one topic';
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM public.topic_overview
        WHERE label = 'Permission test visible topic'
          AND article_count = 1
          AND source_count = 1
    ) THEN
        RAISE EXCEPTION
            'FAIL: counts must include only reader-visible articles';
    END IF;

    IF (SELECT count(*) FROM public.topic_top_articles) <> 1 THEN
        RAISE EXCEPTION
            'FAIL: hidden article or hidden topic membership leaked';
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM public.topic_top_articles
        WHERE link = 'https://example.com/permission-visible'
          AND rank_in_topic = 1
          AND topic_id = (
              SELECT id FROM public.topic_overview
              WHERE label = 'Permission test visible topic'
          )
    ) THEN
        RAISE EXCEPTION
            'FAIL: expected visible article in visible topic at rank 1';
    END IF;

    RAISE NOTICE 'PASS: both views respect reader row-security policies';
END;
$test$;

RESET ROLE;

ROLLBACK;