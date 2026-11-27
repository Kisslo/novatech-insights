-- Skippa and Ändra for a generated draft (#67).
-- Apply after migrations 001–010 and 013. Does not depend on 011 or 012.
-- Test locally before applying to shared Supabase.

BEGIN;

CREATE FUNCTION public.keep_draft(
    p_post_id bigint,
    p_version integer
)
RETURNS TABLE (draft_id bigint, version integer)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $function$
DECLARE
    current_status text;
    latest_draft_id bigint;
    latest_version integer;
BEGIN
    -- Serialize button presses for this post until the transaction ends.
    SELECT post.status
    INTO current_status
    FROM public.posts AS post
    WHERE post.id = p_post_id
    FOR UPDATE;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'Post % does not exist', p_post_id;
    END IF;

    IF current_status <> 'draft_generated' THEN
        RAISE EXCEPTION
            'Post % cannot be kept in status %',
            p_post_id, current_status;
    END IF;

    SELECT draft.id, draft.version
    INTO latest_draft_id, latest_version
    FROM public.post_drafts AS draft
    WHERE draft.post_id = p_post_id
    ORDER BY draft.version DESC
    LIMIT 1;

    IF latest_version IS NULL
       OR p_version IS DISTINCT FROM latest_version THEN
        RAISE EXCEPTION
            'Post % cannot be kept: version % is not the latest draft',
            p_post_id, p_version;
    END IF;

    UPDATE public.posts
    SET status = 'draft_kept'
    WHERE id = p_post_id;

    RETURN QUERY SELECT latest_draft_id, latest_version;
END;
$function$;

CREATE FUNCTION public.request_draft_changes(
    p_post_id bigint,
    p_version integer,
    p_change_request text
)
RETURNS TABLE (draft_id bigint, version integer)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $function$
DECLARE
    current_status text;
    latest_draft_id bigint;
    latest_version integer;
BEGIN
    SELECT post.status
    INTO current_status
    FROM public.posts AS post
    WHERE post.id = p_post_id
    FOR UPDATE;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'Post % does not exist', p_post_id;
    END IF;

    IF current_status <> 'draft_generated' THEN
        RAISE EXCEPTION
            'Post % cannot receive changes in status %',
            p_post_id, current_status;
    END IF;

    SELECT draft.id, draft.version
    INTO latest_draft_id, latest_version
    FROM public.post_drafts AS draft
    WHERE draft.post_id = p_post_id
    ORDER BY draft.version DESC
    LIMIT 1;

    IF latest_version IS NULL
       OR p_version IS DISTINCT FROM latest_version THEN
        RAISE EXCEPTION
            'Post % cannot receive changes: version % is not the latest draft',
            p_post_id, p_version;
    END IF;

    IF p_change_request IS NULL OR p_change_request !~ '[^[:space:]]' THEN
        RAISE EXCEPTION
            'Post % cannot receive changes: the change request is empty',
            p_post_id;
    END IF;

    -- The request belongs to the version Kisslo read.
    UPDATE public.post_drafts
    SET change_request = p_change_request
    WHERE id = latest_draft_id;

    -- save_post_draft accepts changes_requested and saves the next version.
    UPDATE public.posts
    SET status = 'changes_requested'
    WHERE id = p_post_id;

    RETURN QUERY SELECT latest_draft_id, latest_version;
END;
$function$;

REVOKE ALL ON FUNCTION public.keep_draft(bigint, integer) FROM PUBLIC;

REVOKE ALL ON FUNCTION public.request_draft_changes(
    bigint, integer, text
) FROM PUBLIC;

-- Only the backend may call the button functions.
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
            'REVOKE ALL ON FUNCTION public.keep_draft'
            '(bigint, integer) FROM %I',
            role_name
        );

        EXECUTE format(
            'REVOKE ALL ON FUNCTION public.request_draft_changes'
            '(bigint, integer, text) FROM %I',
            role_name
        );
    END LOOP;

    IF EXISTS (
        SELECT 1 FROM pg_roles WHERE rolname = 'service_role'
    ) THEN
        GRANT EXECUTE ON FUNCTION public.keep_draft(
            bigint, integer
        ) TO service_role;

        GRANT EXECUTE ON FUNCTION public.request_draft_changes(
            bigint, integer, text
        ) TO service_role;
    ELSE
        RAISE NOTICE
            'service_role does not exist; backend grants were skipped';
    END IF;
END;
$permissions$;

COMMENT ON FUNCTION public.keep_draft(bigint, integer) IS
'Skippa: moves draft_generated to draft_kept. p_version must be the
latest draft. The draft stays in post_drafts; nothing is published.';

COMMENT ON FUNCTION public.request_draft_changes(bigint, integer, text) IS
'Ändra: saves Kisslo''s change request on the latest draft and moves
draft_generated to changes_requested. save_post_draft then saves the
next version.';

COMMIT;
