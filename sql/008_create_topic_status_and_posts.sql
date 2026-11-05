-- Topic status and Telegram selection storage.
-- Apply after migrations 002–007.
-- Test locally before applying to shared Supabase.

BEGIN;

ALTER TABLE public.topics
ADD COLUMN status text NOT NULL DEFAULT 'new';

ALTER TABLE public.topics
ADD CONSTRAINT topics_status_allowed
CHECK (status IN ('new', 'shown', 'selected', 'skipped'));

CREATE TABLE public.posts (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,

    topic_id bigint NOT NULL,
    status text NOT NULL DEFAULT 'awaiting_angle',
    kisslo_angle text,

    telegram_chat_id bigint NOT NULL,
    telegram_prompt_message_id bigint,

    CONSTRAINT posts_topic_unique
        UNIQUE (topic_id),

    CONSTRAINT posts_topic_fk
        FOREIGN KEY (topic_id)
        REFERENCES public.topics(id)
        ON DELETE RESTRICT,

    CONSTRAINT posts_status_allowed
        CHECK (status IN ('awaiting_angle', 'angle_received')),

    CONSTRAINT posts_angle_matches_status
        CHECK (
            (
                status = 'awaiting_angle'
                AND kisslo_angle IS NULL
            )
            OR
            (
                status = 'angle_received'
                AND kisslo_angle IS NOT NULL
                AND kisslo_angle ~ '[^[:space:]]'
            )
        ),

    CONSTRAINT posts_chat_id_valid
        CHECK (telegram_chat_id <> 0),

    CONSTRAINT posts_prompt_message_id_valid
        CHECK (
            telegram_prompt_message_id IS NULL
            OR telegram_prompt_message_id > 0
        ),

    CONSTRAINT posts_telegram_prompt_unique
        UNIQUE (telegram_chat_id, telegram_prompt_message_id)
);

ALTER TABLE public.posts ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON TABLE public.posts FROM PUBLIC;
REVOKE ALL ON SEQUENCE public.posts_id_seq FROM PUBLIC;

-- Remove automatic grants from application roles when present.
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
            'REVOKE ALL ON TABLE public.posts FROM %I',
            role_name
        );

        EXECUTE format(
            'REVOKE ALL ON SEQUENCE public.posts_id_seq FROM %I',
            role_name
        );
    END LOOP;

    IF EXISTS (
        SELECT 1 FROM pg_roles WHERE rolname = 'service_role'
    ) THEN
        GRANT UPDATE (status)
        ON public.topics TO service_role;

        GRANT SELECT
        ON public.posts TO service_role;

        GRANT INSERT (
            topic_id,
            status,
            kisslo_angle,
            telegram_chat_id,
            telegram_prompt_message_id
        ) ON public.posts TO service_role;

        GRANT UPDATE (
            status,
            kisslo_angle,
            telegram_prompt_message_id
        ) ON public.posts TO service_role;

        GRANT USAGE
        ON SEQUENCE public.posts_id_seq TO service_role;
    ELSE
        RAISE NOTICE
            'service_role does not exist; new backend grants were skipped';
    END IF;
END;
$permissions$;

COMMENT ON COLUMN public.topics.status IS
'Telegram workflow state: new, shown, selected or skipped.
Existing topics start as new. n8n manages transitions.
This is not a topic freshness or retirement marker.';

COMMENT ON TABLE public.posts IS
'One selection per topic. Stores a pending or received Kisslo angle.
Repeated selection must reuse the existing row.
Later reselection and content-generation states require a separate design.';

COMMENT ON COLUMN public.posts.telegram_prompt_message_id IS
'NULL while the prompt has not been recorded.
n8n records the message ID after sending the question.
Match replies using both telegram_chat_id and this message ID.';

COMMENT ON COLUMN public.posts.kisslo_angle IS
'NULL while awaiting_angle. Supply a nonblank angle and set
status to angle_received together in the same update.';

COMMIT;