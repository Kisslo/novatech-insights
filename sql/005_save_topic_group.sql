-- Draft migration for issue #26.
-- Test locally before deployment.
-- Backend permissions are configured separately.

BEGIN;

CREATE OR REPLACE FUNCTION public.save_topic_group(p_news_ids bigint[])
RETURNS bigint
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = pg_catalog
AS $function$
DECLARE
    article_ids bigint[];
    saved_topic_id bigint;
BEGIN
    IF p_news_ids IS NULL
       OR cardinality(p_news_ids) = 0 THEN
        RAISE EXCEPTION 'Article IDs must not be empty';
    END IF;

    IF array_ndims(p_news_ids) <> 1 THEN
        RAISE EXCEPTION 'Article IDs must be a one-dimensional array';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM unnest(p_news_ids) AS supplied(news_id)
        WHERE news_id IS NULL OR news_id <= 0
    ) THEN
        RAISE EXCEPTION 'Article IDs must be positive and not NULL';
    END IF;

    SELECT array_agg(news_id ORDER BY news_id)
    INTO article_ids
    FROM (
        SELECT DISTINCT news_id
        FROM unnest(p_news_ids) AS supplied(news_id)
    ) AS unique_ids;

    IF cardinality(article_ids) < 2 THEN
        RAISE EXCEPTION 'A group needs at least two distinct articles';
    END IF;

    -- Serialize calls to this function until the transaction ends.
    -- Group membership writers must use this function.
    -- These numbers identify the application's group-saving lock.
    PERFORM pg_catalog.pg_advisory_xact_lock(260039, 1);

    -- Reuse an existing topic with exactly these article IDs.
    SELECT membership.topic_id
    INTO saved_topic_id
    FROM public.topic_articles AS membership
    JOIN public.topics AS topic
        ON topic.id = membership.topic_id
    GROUP BY membership.topic_id
    HAVING array_agg(
        membership.news_id ORDER BY membership.news_id
    ) = article_ids
    ORDER BY membership.topic_id
    LIMIT 1;

    IF saved_topic_id IS NOT NULL THEN
        RETURN saved_topic_id;
    END IF;

    -- Labels and score fields remain NULL for downstream steps.
    INSERT INTO public.topics DEFAULT VALUES
    RETURNING id INTO saved_topic_id;

    INSERT INTO public.topic_articles (topic_id, news_id)
    SELECT saved_topic_id, news_id
    FROM unnest(article_ids) AS supplied(news_id);

    -- Foreign keys reject IDs that do not exist in public.news.
    -- Any error rolls back the function's writes.
    RETURN saved_topic_id;
END;
$function$;

REVOKE ALL ON FUNCTION public.save_topic_group(bigint[]) FROM PUBLIC;

-- Remove automatic function grants when Supabase roles exist.
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
            'REVOKE ALL ON FUNCTION public.save_topic_group(bigint[]) FROM %I',
            role_name
        );
    END LOOP;
END;
$permissions$;

COMMENT ON FUNCTION public.save_topic_group(bigint[]) IS
'Saves a group and its memberships atomically. Reuses exact article-ID
sets without modifying labels or scores. Changed memberships create a
new topic; existing topics are not deleted. Backend grants are separate.';

COMMIT;