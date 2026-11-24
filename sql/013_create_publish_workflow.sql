-- Publishing workflow for WordPress (#81).
-- Apply after migrations 001–010. Does not depend on 011 or 012.
-- Test locally before applying to shared Supabase.
-- Check first that no existing post has status published.

BEGIN;

-- Allow draft_kept (Skippa). publish_requested and published exist in 010.
ALTER TABLE public.posts
DROP CONSTRAINT posts_status_allowed;

ALTER TABLE public.posts
ADD CONSTRAINT posts_status_allowed CHECK (
    status IN (
        'awaiting_angle',
        'angle_received',
        'draft_generated',
        'awaiting_approval',
        'approved',
        'changes_requested',
        'publish_requested',
        'published',
        'draft_kept'
    )
);

ALTER TABLE public.posts
DROP CONSTRAINT posts_angle_matches_status;

ALTER TABLE public.posts
ADD CONSTRAINT posts_angle_matches_status CHECK (
    (
        status = 'awaiting_angle'
        AND kisslo_angle IS NULL
    )
    OR
    (
        status IN (
            'angle_received',
            'draft_generated',
            'awaiting_approval',
            'approved',
            'changes_requested',
            'publish_requested',
            'published',
            'draft_kept'
        )
        AND kisslo_angle IS NOT NULL
        AND kisslo_angle ~ '[^[:space:]]'
    )
);

-- Publication details. Set only by mark_post_published.
ALTER TABLE public.posts
    ADD COLUMN approved_draft_id bigint,
    ADD COLUMN wordpress_post_id bigint,
    ADD COLUMN published_url text,
    ADD COLUMN published_at timestamptz;

ALTER TABLE public.posts
    ADD CONSTRAINT posts_approved_draft_fk
        FOREIGN KEY (approved_draft_id)
        REFERENCES public.post_drafts(id)
        ON DELETE RESTRICT,

    ADD CONSTRAINT posts_wordpress_post_id_valid
        CHECK (wordpress_post_id IS NULL OR wordpress_post_id > 0),

    ADD CONSTRAINT posts_wordpress_post_unique
        UNIQUE (wordpress_post_id),

    ADD CONSTRAINT posts_published_url_valid
        CHECK (
            published_url IS NULL
            OR published_url ~ '^https?://[^[:space:]]+$'
        ),

    -- Published posts have every detail. Other posts have none.
    ADD CONSTRAINT posts_publication_matches_status
        CHECK (
            (
                status = 'published'
                AND approved_draft_id IS NOT NULL
                AND wordpress_post_id IS NOT NULL
                AND published_url IS NOT NULL
                AND published_at IS NOT NULL
            )
            OR
            (
                status <> 'published'
                AND approved_draft_id IS NULL
                AND wordpress_post_id IS NULL
                AND published_url IS NULL
                AND published_at IS NULL
            )
        );

-- Kisslo's change request for a specific draft version (Ändra, #67).
ALTER TABLE public.post_drafts
    ADD COLUMN change_request text,
    ADD CONSTRAINT post_drafts_change_request_valid
        CHECK (
            change_request IS NULL
            OR change_request ~ '[^[:space:]]'
        );

CREATE FUNCTION public.request_publish(
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
    -- Serialize publishing for this post until the transaction ends.
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
            'Post % cannot be published in status %',
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
            'Post % cannot be published: version % is not the latest draft',
            p_post_id, p_version;
    END IF;

    UPDATE public.posts
    SET status = 'publish_requested'
    WHERE id = p_post_id;

    RETURN QUERY SELECT latest_draft_id, latest_version;
END;
$function$;

CREATE FUNCTION public.mark_post_published(
    p_post_id bigint,
    p_draft_id bigint,
    p_wordpress_post_id bigint,
    p_published_url text
)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $function$
DECLARE
    current_status text;
    latest_draft_id bigint;
BEGIN
    SELECT post.status
    INTO current_status
    FROM public.posts AS post
    WHERE post.id = p_post_id
    FOR UPDATE;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'Post % does not exist', p_post_id;
    END IF;

    -- A published post can never be marked published again.
    IF current_status <> 'publish_requested' THEN
        RAISE EXCEPTION
            'Post % cannot be marked published in status %',
            p_post_id, current_status;
    END IF;

    -- No new draft can be saved in publish_requested,
    -- so the latest draft is the one that was requested.
    SELECT draft.id
    INTO latest_draft_id
    FROM public.post_drafts AS draft
    WHERE draft.post_id = p_post_id
    ORDER BY draft.version DESC
    LIMIT 1;

    IF p_draft_id IS DISTINCT FROM latest_draft_id THEN
        RAISE EXCEPTION
            'Post % cannot be marked published: draft % is not the latest draft',
            p_post_id, p_draft_id;
    END IF;

    UPDATE public.posts
    SET status = 'published',
        approved_draft_id = p_draft_id,
        wordpress_post_id = p_wordpress_post_id,
        published_url = p_published_url,
        published_at = now()
    WHERE id = p_post_id;
END;
$function$;

CREATE FUNCTION public.cancel_publish_request(
    p_post_id bigint
)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $function$
DECLARE
    current_status text;
BEGIN
    SELECT post.status
    INTO current_status
    FROM public.posts AS post
    WHERE post.id = p_post_id
    FOR UPDATE;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'Post % does not exist', p_post_id;
    END IF;

    IF current_status <> 'publish_requested' THEN
        RAISE EXCEPTION
            'Post % cannot cancel publishing in status %',
            p_post_id, current_status;
    END IF;

    UPDATE public.posts
    SET status = 'draft_generated'
    WHERE id = p_post_id;
END;
$function$;

REVOKE ALL ON FUNCTION public.request_publish(bigint, integer)
FROM PUBLIC;

REVOKE ALL ON FUNCTION public.mark_post_published(
    bigint, bigint, bigint, text
) FROM PUBLIC;

REVOKE ALL ON FUNCTION public.cancel_publish_request(bigint)
FROM PUBLIC;

-- Only the backend may call the publishing functions.
-- The backend reads the new columns through its existing SELECT grants.
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
            'REVOKE ALL ON FUNCTION public.request_publish'
            '(bigint, integer) FROM %I',
            role_name
        );

        EXECUTE format(
            'REVOKE ALL ON FUNCTION public.mark_post_published'
            '(bigint, bigint, bigint, text) FROM %I',
            role_name
        );

        EXECUTE format(
            'REVOKE ALL ON FUNCTION public.cancel_publish_request'
            '(bigint) FROM %I',
            role_name
        );
    END LOOP;

    IF EXISTS (
        SELECT 1 FROM pg_roles WHERE rolname = 'service_role'
    ) THEN
        GRANT EXECUTE ON FUNCTION public.request_publish(
            bigint, integer
        ) TO service_role;

        GRANT EXECUTE ON FUNCTION public.mark_post_published(
            bigint, bigint, bigint, text
        ) TO service_role;

        GRANT EXECUTE ON FUNCTION public.cancel_publish_request(
            bigint
        ) TO service_role;
    ELSE
        RAISE NOTICE
            'service_role does not exist; backend grants were skipped';
    END IF;
END;
$permissions$;

COMMENT ON FUNCTION public.request_publish(bigint, integer) IS
'Locks the post and moves draft_generated to publish_requested.
p_version must be the latest draft version.
Returns the draft to send to WordPress.';

COMMENT ON FUNCTION public.mark_post_published(
    bigint, bigint, bigint, text
) IS
'Moves publish_requested to published and stores the WordPress
post ID, URL, approved draft and published_at. Never runs twice.';

COMMENT ON FUNCTION public.cancel_publish_request(bigint) IS
'Moves publish_requested back to draft_generated. Use only when
WordPress certainly did not create the post.';

COMMENT ON COLUMN public.post_drafts.change_request IS
'Kisslo''s requested changes for this draft version (Ändra, #67).
NULL when no change was requested.';

COMMIT;
