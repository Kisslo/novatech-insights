-- Let Skippa work after a failed Ändra (#67).
-- keep_draft now accepts draft_generated and changes_requested.
-- request_publish is unchanged: a version with requested changes
-- must not be published.
-- Apply after migration 014.

BEGIN;

CREATE OR REPLACE FUNCTION public.keep_draft(
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

    -- changes_requested: Ändra failed before a new version was saved.
    IF current_status NOT IN ('draft_generated', 'changes_requested') THEN
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

-- CREATE OR REPLACE keeps the grants from 014. Set them again anyway,
-- so the result does not depend on the earlier state.
REVOKE ALL ON FUNCTION public.keep_draft(bigint, integer) FROM PUBLIC;

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
    END LOOP;

    IF EXISTS (
        SELECT 1 FROM pg_roles WHERE rolname = 'service_role'
    ) THEN
        GRANT EXECUTE ON FUNCTION public.keep_draft(
            bigint, integer
        ) TO service_role;
    ELSE
        RAISE NOTICE
            'service_role does not exist; backend grants were skipped';
    END IF;
END;
$permissions$;

COMMENT ON FUNCTION public.keep_draft(bigint, integer) IS
'Skippa: moves draft_generated or changes_requested to draft_kept.
p_version must be the latest draft. The draft stays in post_drafts;
nothing is published.';

COMMIT;
