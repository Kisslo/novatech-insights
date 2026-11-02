-- Local/CI test only. Never run in Supabase.
\set ON_ERROR_STOP on

BEGIN;

DO $setup$
BEGIN
    IF current_database() NOT IN (
        'novatech_test',
        'novatech_permissions_test'
    ) THEN
        RAISE EXCEPTION 'Run only in a local test database';
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_roles WHERE rolname = 'service_role'
    ) THEN
        CREATE ROLE service_role
            NOLOGIN NOSUPERUSER BYPASSRLS;
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_roles
        WHERE rolname = 'service_role'
          AND NOT rolsuper
          AND rolbypassrls
    ) THEN
        RAISE EXCEPTION
            'Expected service_role to bypass RLS without being a superuser';
    END IF;
END;
$setup$;

-- Reset direct grants on the new objects for this test.
REVOKE ALL ON TABLE
    public.topics,
    public.topic_articles,
    public.topic_overview,
    public.topic_top_articles
FROM service_role;

REVOKE ALL ON SEQUENCE public.topics_id_seq FROM service_role;
REVOKE ALL ON FUNCTION public.save_topic_group(bigint[])
FROM service_role;

-- Proposed permissions shared by backend programs.
GRANT USAGE ON SCHEMA public TO service_role;

GRANT SELECT ON TABLE
    public.news,
    public.topics,
    public.topic_articles,
    public.topic_overview,
    public.topic_top_articles
TO service_role;

GRANT INSERT ON TABLE
    public.topics,
    public.topic_articles
TO service_role;

GRANT UPDATE (
    score,
    score_calculated_at,
    score_version,
    score_breakdown
) ON public.topics TO service_role;

GRANT USAGE ON SEQUENCE public.topics_id_seq TO service_role;

GRANT EXECUTE ON FUNCTION public.save_topic_group(bigint[])
TO service_role;

-- Create fixture articles as the test administrator.
CREATE TEMP TABLE backend_test_articles (
    news_id bigint PRIMARY KEY
) ON COMMIT DROP;

WITH inserted AS (
    INSERT INTO public.news (title, link, source, published)
    VALUES
        (
            'Backend permission article A',
            'https://example.com/backend-permission-test-a',
            'Backend Source A',
            now()
        ),
        (
            'Backend permission article B',
            'https://example.com/backend-permission-test-b',
            'Backend Source B',
            now()
        )
    RETURNING id
)
INSERT INTO backend_test_articles (news_id)
SELECT id FROM inserted;

GRANT SELECT ON backend_test_articles TO service_role;

-- All following assertions run as the backend role.
SET LOCAL ROLE service_role;

DO $test$
DECLARE
    article_ids bigint[];
    topic_id_saved bigint;
    topic_id_repeated bigint;
    blocked boolean;
BEGIN
    IF current_user <> 'service_role' THEN
        RAISE EXCEPTION 'FAIL: test is not running as service_role';
    END IF;

    SELECT array_agg(news_id ORDER BY news_id)
    INTO article_ids
    FROM backend_test_articles;

    IF (
        SELECT count(*)
        FROM public.news
        WHERE id = ANY(article_ids)
    ) <> 2 THEN
        RAISE EXCEPTION 'FAIL: backend cannot read fixture articles';
    END IF;

    topic_id_saved := public.save_topic_group(article_ids);

    IF (
        SELECT array_agg(news_id ORDER BY news_id)
        FROM public.topic_articles
        WHERE topic_id = topic_id_saved
    ) IS DISTINCT FROM article_ids THEN
        RAISE EXCEPTION 'FAIL: backend did not save all memberships';
    END IF;

    topic_id_repeated := public.save_topic_group(
        ARRAY[article_ids[2], article_ids[1]]
    );

    IF topic_id_repeated IS DISTINCT FROM topic_id_saved THEN
        RAISE EXCEPTION 'FAIL: repeated backend save created another topic';
    END IF;

    RAISE NOTICE
        'PASS: backend reads news and saves/reuses a complete group';

    UPDATE public.topics
    SET score = 0.8,
        score_calculated_at = now(),
        score_version = 'backend-test-v1',
        score_breakdown = '{"test": true}'::jsonb
    WHERE id = topic_id_saved;

    IF NOT EXISTS (
        SELECT 1
        FROM public.topics
        WHERE id = topic_id_saved
          AND score = 0.8
          AND score_calculated_at = now()
          AND score_version = 'backend-test-v1'
          AND score_breakdown = '{"test": true}'::jsonb
    ) THEN
        RAISE EXCEPTION 'FAIL: backend could not update ranking fields';
    END IF;

    RAISE NOTICE 'PASS: backend updates ranking fields';

    IF NOT EXISTS (
        SELECT 1
        FROM public.topic_overview
        WHERE id = topic_id_saved
          AND article_count = 2
          AND source_count = 2
    ) THEN
        RAISE EXCEPTION 'FAIL: backend cannot read full topic counts';
    END IF;

    IF (
        SELECT count(*)
        FROM public.topic_top_articles
        WHERE topic_id = topic_id_saved
    ) <> 2 THEN
        RAISE EXCEPTION 'FAIL: backend cannot read selected articles';
    END IF;

    RAISE NOTICE 'PASS: backend reads both topic views';

    blocked := false;
    BEGIN
        UPDATE public.topics
        SET label = 'Unauthorized change'
        WHERE id = topic_id_saved;
    EXCEPTION
        WHEN insufficient_privilege THEN
            blocked := true;
    END;

    IF NOT blocked THEN
        RAISE EXCEPTION 'FAIL: backend can update labels';
    END IF;

    blocked := false;
    BEGIN
        UPDATE public.topic_articles
        SET news_id = news_id
        WHERE topic_id = topic_id_saved;
    EXCEPTION
        WHEN insufficient_privilege THEN
            blocked := true;
    END;

    IF NOT blocked THEN
        RAISE EXCEPTION 'FAIL: backend can update memberships';
    END IF;

    blocked := false;
    BEGIN
        DELETE FROM public.topic_articles
        WHERE topic_id = topic_id_saved;
    EXCEPTION
        WHEN insufficient_privilege THEN
            blocked := true;
    END;

    IF NOT blocked THEN
        RAISE EXCEPTION 'FAIL: backend can delete memberships';
    END IF;

    -- No matching row: checks DELETE permission without triggering FKs.
    blocked := false;
    BEGIN
        DELETE FROM public.topics WHERE id = topic_id_saved AND false;
    EXCEPTION
        WHEN insufficient_privilege THEN
            blocked := true;
    END;

    IF NOT blocked THEN
        RAISE EXCEPTION 'FAIL: backend can delete topics';
    END IF;

    RAISE NOTICE
        'PASS: label updates, membership updates and deletes are denied';
END;
$test$;

RESET ROLE;
ROLLBACK;