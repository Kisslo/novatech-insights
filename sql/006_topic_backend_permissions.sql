-- Draft backend permissions for issue #26.
-- Test locally before deployment.
-- All programs using service_role share these permissions.

BEGIN;

DO $permissions$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_roles WHERE rolname = 'service_role'
    ) THEN
        RAISE NOTICE
            'service_role does not exist; backend grants were skipped';
        RETURN;
    END IF;

    GRANT USAGE ON SCHEMA public TO service_role;

    -- Preserve existing news permissions and add read access.
    GRANT SELECT ON public.news TO service_role;

    REVOKE ALL ON TABLE
        public.topics,
        public.topic_articles,
        public.topic_overview,
        public.topic_top_articles
    FROM service_role;

    REVOKE ALL ON SEQUENCE public.topics_id_seq
    FROM service_role;

    REVOKE ALL ON FUNCTION public.save_topic_group(bigint[])
    FROM service_role;

    GRANT SELECT ON TABLE
        public.topics,
        public.topic_articles,
        public.topic_overview,
        public.topic_top_articles
    TO service_role;

    GRANT INSERT ON TABLE
        public.topics,
        public.topic_articles
    TO service_role;

    GRANT USAGE ON SEQUENCE public.topics_id_seq
    TO service_role;

    GRANT EXECUTE ON FUNCTION public.save_topic_group(bigint[])
    TO service_role;

    GRANT UPDATE (
        score,
        score_calculated_at,
        score_version,
        score_breakdown
    ) ON public.topics TO service_role;
END;
$permissions$;

COMMIT;