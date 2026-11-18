-- Versioned article and LinkedIn drafts.
-- Apply after migrations 001–009.
-- Test locally before shared deployment.
-- Resolve the existing shared post_drafts table before applying.

BEGIN;

-- Preserve the existing statuses and allow the content workflow.
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
        'published'
    )
);

-- Later states must retain a nonblank Kisslo angle.
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
            'published'
        )
        AND kisslo_angle IS NOT NULL
        AND kisslo_angle ~ '[^[:space:]]'
    )
);

CREATE TABLE public.post_drafts (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    post_id bigint NOT NULL
        REFERENCES public.posts(id) ON DELETE RESTRICT,
    version integer NOT NULL CHECK (version > 0),
    article_text text NOT NULL
        CHECK (article_text ~ '[^[:space:]]'),
    linkedin_text text NOT NULL
        CHECK (linkedin_text ~ '[^[:space:]]'),
    reviewer_notes text NOT NULL,
    source_news_ids bigint[] NOT NULL,
    stance text NOT NULL CHECK (stance IN ('agree', 'rebut')),
    created_at timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT post_drafts_post_version_unique
        UNIQUE (post_id, version)
);

ALTER TABLE public.post_drafts ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON TABLE public.post_drafts FROM PUBLIC;

-- Resolve the new table's actual identity sequence.
-- A legacy table may still own public.post_drafts_id_seq.
DO $sequence_permissions$
DECLARE
    sequence_name regclass;
    role_name text;
BEGIN
    sequence_name :=
        pg_get_serial_sequence('public.post_drafts', 'id')::regclass;

    IF sequence_name IS NULL THEN
        RAISE EXCEPTION 'Draft identity sequence was not found';
    END IF;

    EXECUTE format(
        'REVOKE ALL ON SEQUENCE %s FROM PUBLIC',
        sequence_name
    );

    FOR role_name IN
        SELECT rolname
        FROM pg_roles
        WHERE rolname IN ('anon', 'authenticated', 'service_role')
    LOOP
        EXECUTE format(
            'REVOKE ALL ON SEQUENCE %s FROM %I',
            sequence_name,
            role_name
        );
    END LOOP;
END;
$sequence_permissions$;

CREATE FUNCTION public.save_post_draft(
    p_post_id bigint,
    p_article_text text,
    p_linkedin_text text,
    p_reviewer_notes text,
    p_source_news_ids bigint[],
    p_stance text
)
RETURNS TABLE (draft_id bigint, version integer)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $function$
DECLARE
    current_status text;
    next_version integer;
    saved_draft_id bigint;
BEGIN
    -- Serialize draft saves for this post until the transaction ends.
    SELECT post.status
    INTO current_status
    FROM public.posts AS post
    WHERE post.id = p_post_id
    FOR UPDATE;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'Post % does not exist', p_post_id;
    END IF;

    -- A new draft requires an angle or an explicit change request.
    -- After a successful save, draft_generated blocks another save.
    IF current_status NOT IN (
        'angle_received',
        'changes_requested'
    ) THEN
        RAISE EXCEPTION
            'Post % cannot receive a draft in status %',
            p_post_id, current_status;
    END IF;

    SELECT COALESCE(MAX(draft.version), 0) + 1
    INTO next_version
    FROM public.post_drafts AS draft
    WHERE draft.post_id = p_post_id;

    INSERT INTO public.post_drafts (
        post_id,
        version,
        article_text,
        linkedin_text,
        reviewer_notes,
        source_news_ids,
        stance
    )
    VALUES (
        p_post_id,
        next_version,
        p_article_text,
        p_linkedin_text,
        p_reviewer_notes,
        p_source_news_ids,
        p_stance
    )
    RETURNING id INTO saved_draft_id;

    UPDATE public.posts
    SET status = 'draft_generated'
    WHERE id = p_post_id;

    RETURN QUERY SELECT saved_draft_id, next_version;
END;
$function$;

REVOKE ALL ON FUNCTION public.save_post_draft(
    bigint, text, text, text, bigint[], text
) FROM PUBLIC;

-- Remove automatic application grants.
-- Draft writes must go through save_post_draft.
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
            'REVOKE ALL ON TABLE public.post_drafts FROM %I',
            role_name
        );

        EXECUTE format(
            'REVOKE ALL ON FUNCTION public.save_post_draft'
            '(bigint, text, text, text, bigint[], text) FROM %I',
            role_name
        );
    END LOOP;

    IF EXISTS (
        SELECT 1 FROM pg_roles WHERE rolname = 'service_role'
    ) THEN
        GRANT USAGE ON SCHEMA public TO service_role;

        GRANT SELECT ON public.post_drafts TO service_role;

        GRANT EXECUTE ON FUNCTION public.save_post_draft(
            bigint, text, text, text, bigint[], text
        ) TO service_role;
    ELSE
        RAISE NOTICE
            'service_role does not exist; backend grants were skipped';
    END IF;
END;
$permissions$;

COMMENT ON TABLE public.post_drafts IS
'Versioned article and LinkedIn drafts. Backend writes use
save_post_draft. Reviewer notes are not publishable content.';

COMMENT ON FUNCTION public.save_post_draft(
    bigint, text, text, text, bigint[], text
) IS
'Saves the next draft version and updates post status atomically.
Locks the post to serialize version allocation.
Accepts only angle_received or changes_requested.
Repeated saves from draft_generated are rejected.
This is a status guard, not request-ID-based idempotency.
Does not approve or publish content.';

COMMIT;