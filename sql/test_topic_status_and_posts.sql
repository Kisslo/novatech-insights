-- Local/CI only. Run after migration 008 as postgres.
-- All fixture records and temporary grants are rolled back.
\set ON_ERROR_STOP on

BEGIN;

DO $setup$
DECLARE
    role_name text;
BEGIN
    IF current_database() NOT IN (
        'novatech_test',
        'novatech_permissions_test'
    ) THEN
        RAISE EXCEPTION 'Run only in a local or CI test database';
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_roles
        WHERE rolname = 'service_role'
          AND NOT rolsuper
          AND rolbypassrls
    ) THEN
        RAISE EXCEPTION 'Expected a non-superuser backend with BYPASSRLS';
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_class
        WHERE oid = 'public.posts'::regclass
          AND relrowsecurity
    ) THEN
        RAISE EXCEPTION 'FAIL: posts row security is not enabled';
    END IF;

    FOR role_name IN
        SELECT rolname
        FROM pg_roles
        WHERE rolname IN ('anon', 'authenticated')
    LOOP
        IF has_any_column_privilege(
            role_name, 'public.posts', 'SELECT'
        ) OR has_any_column_privilege(
            role_name, 'public.posts', 'INSERT'
        ) OR has_any_column_privilege(
            role_name, 'public.posts', 'UPDATE'
        ) OR has_table_privilege(
            role_name, 'public.posts', 'DELETE'
        ) THEN
            RAISE EXCEPTION
                'FAIL: unexpected posts access for %', role_name;
        END IF;
    END LOOP;
END;
$setup$;

CREATE TEMP TABLE workflow_test_topics (
    label text PRIMARY KEY,
    topic_id bigint NOT NULL
) ON COMMIT DROP;

WITH inserted AS (
    INSERT INTO public.topics (label)
    VALUES
        ('Workflow test A'),
        ('Workflow test B'),
        ('Workflow test C')
    RETURNING id, label
)
INSERT INTO workflow_test_topics (label, topic_id)
SELECT label, id FROM inserted;

GRANT SELECT ON workflow_test_topics TO service_role;

SET LOCAL ROLE service_role;

DO $test$
DECLARE
    topic_a bigint;
    topic_b bigint;
    topic_c bigint;
    post_a bigint;
    post_b bigint;
    matched_post bigint;
    rejected boolean;
BEGIN
    IF current_user <> 'service_role' THEN
        RAISE EXCEPTION 'FAIL: test must run as service_role';
    END IF;

    SELECT topic_id INTO STRICT topic_a
    FROM workflow_test_topics WHERE label = 'Workflow test A';

    SELECT topic_id INTO STRICT topic_b
    FROM workflow_test_topics WHERE label = 'Workflow test B';

    SELECT topic_id INTO STRICT topic_c
    FROM workflow_test_topics WHERE label = 'Workflow test C';

    IF (
        SELECT count(*)
        FROM public.topics
        WHERE id IN (topic_a, topic_b, topic_c)
          AND status = 'new'
    ) <> 3 THEN
        RAISE EXCEPTION 'FAIL: new topics must default to new';
    END IF;

    UPDATE public.topics SET status = 'shown' WHERE id = topic_a;

    IF NOT EXISTS (
        SELECT 1 FROM public.topics
        WHERE id = topic_a AND status = 'shown'
    ) THEN
        RAISE EXCEPTION 'FAIL: backend cannot mark a topic shown';
    END IF;

    UPDATE public.topics SET status = 'selected' WHERE id = topic_a;
    UPDATE public.topics SET status = 'skipped' WHERE id = topic_c;

    IF NOT EXISTS (
        SELECT 1 FROM public.topics
        WHERE id = topic_a AND status = 'selected'
    ) OR NOT EXISTS (
        SELECT 1 FROM public.topics
        WHERE id = topic_c AND status = 'skipped'
    ) THEN
        RAISE EXCEPTION 'FAIL: backend cannot save selected/skipped';
    END IF;

    rejected := false;
    BEGIN
        UPDATE public.topics SET status = 'invalid' WHERE id = topic_a;
    EXCEPTION
        WHEN check_violation THEN
            rejected := true;
    END;

    IF NOT rejected THEN
        RAISE EXCEPTION 'FAIL: invalid topic status was accepted';
    END IF;

    RAISE NOTICE 'PASS: topic defaults and backend status updates';

    -- Reserve the selection before the prompt message ID is known.
    INSERT INTO public.posts (topic_id, telegram_chat_id)
    VALUES (topic_a, -100001)
    RETURNING id INTO post_a;

    IF NOT EXISTS (
        SELECT 1 FROM public.posts
        WHERE id = post_a
          AND status = 'awaiting_angle'
          AND kisslo_angle IS NULL
          AND telegram_prompt_message_id IS NULL
    ) THEN
        RAISE EXCEPTION 'FAIL: pending post defaults are incorrect';
    END IF;

    -- Record the message ID returned after sending the question.
    UPDATE public.posts
    SET telegram_prompt_message_id = 101
    WHERE id = post_a;

    rejected := false;
    BEGIN
        INSERT INTO public.posts (topic_id, telegram_chat_id)
        VALUES (topic_a, -100001);
    EXCEPTION
        WHEN unique_violation THEN
            rejected := true;
    END;

    IF NOT rejected THEN
        RAISE EXCEPTION 'FAIL: duplicate topic selection was accepted';
    END IF;

    rejected := false;
    BEGIN
        INSERT INTO public.posts (
            topic_id, telegram_chat_id, telegram_prompt_message_id
        )
        VALUES (topic_b, -100001, 101);
    EXCEPTION
        WHEN unique_violation THEN
            rejected := true;
    END;

    IF NOT rejected THEN
        RAISE EXCEPTION 'FAIL: duplicate chat/prompt pair was accepted';
    END IF;

    -- The same message number in a different chat is valid.
    INSERT INTO public.posts (
        topic_id, telegram_chat_id, telegram_prompt_message_id
    )
    VALUES (topic_b, -100002, 101)
    RETURNING id INTO post_b;

    SELECT id INTO STRICT matched_post
    FROM public.posts
    WHERE telegram_chat_id = -100001
      AND telegram_prompt_message_id = 101
      AND status = 'awaiting_angle';

    IF matched_post IS DISTINCT FROM post_a THEN
        RAISE EXCEPTION 'FAIL: reply matched the wrong post';
    END IF;

    UPDATE public.posts
    SET kisslo_angle = 'Focus on Swedish small businesses.',
        status = 'angle_received'
    WHERE id = matched_post
      AND status = 'awaiting_angle';

    IF NOT EXISTS (
        SELECT 1 FROM public.posts
        WHERE id = post_a
          AND topic_id = topic_a
          AND status = 'angle_received'
          AND kisslo_angle = 'Focus on Swedish small businesses.'
    ) OR NOT EXISTS (
        SELECT 1 FROM public.posts
        WHERE id = post_b
          AND status = 'awaiting_angle'
          AND kisslo_angle IS NULL
    ) THEN
        RAISE EXCEPTION 'FAIL: angle was not saved to the correct post';
    END IF;

    RAISE NOTICE 'PASS: selection, duplicate protection and reply matching';

    rejected := false;
    BEGIN
        UPDATE public.posts
        SET status = 'angle_received'
        WHERE id = post_b;
    EXCEPTION
        WHEN check_violation THEN
            rejected := true;
    END;

    IF NOT rejected THEN
        RAISE EXCEPTION 'FAIL: received status without angle was accepted';
    END IF;

    rejected := false;
    BEGIN
        UPDATE public.posts
        SET status = 'angle_received',
            kisslo_angle = E' \t\n '
        WHERE id = post_b;
    EXCEPTION
        WHEN check_violation THEN
            rejected := true;
    END;

    IF NOT rejected THEN
        RAISE EXCEPTION 'FAIL: whitespace-only angle was accepted';
    END IF;

    rejected := false;
    BEGIN
        UPDATE public.posts SET status = 'invalid' WHERE id = post_b;
    EXCEPTION
        WHEN check_violation THEN
            rejected := true;
    END;

    IF NOT rejected THEN
        RAISE EXCEPTION 'FAIL: invalid post status was accepted';
    END IF;

    RAISE NOTICE 'PASS: invalid post states and empty angles are rejected';

    rejected := false;
    BEGIN
        INSERT INTO public.posts (topic_id, telegram_chat_id)
        VALUES (0, -100001);
    EXCEPTION
        WHEN foreign_key_violation THEN
            rejected := true;
    END;

    IF NOT rejected THEN
        RAISE EXCEPTION 'FAIL: missing topic reference was accepted';
    END IF;

    rejected := false;
    BEGIN
        UPDATE public.posts SET topic_id = topic_id WHERE id = post_a;
    EXCEPTION
        WHEN insufficient_privilege THEN
            rejected := true;
    END;

    IF NOT rejected THEN
        RAISE EXCEPTION 'FAIL: backend can change post topic identity';
    END IF;

    rejected := false;
    BEGIN
        UPDATE public.posts
        SET telegram_chat_id = telegram_chat_id
        WHERE id = post_a;
    EXCEPTION
        WHEN insufficient_privilege THEN
            rejected := true;
    END;

    IF NOT rejected THEN
        RAISE EXCEPTION 'FAIL: backend can change post chat identity';
    END IF;

    rejected := false;
    BEGIN
        DELETE FROM public.posts WHERE id = post_a;
    EXCEPTION
        WHEN insufficient_privilege THEN
            rejected := true;
    END;

    IF NOT rejected THEN
        RAISE EXCEPTION 'FAIL: backend can delete posts';
    END IF;

    RAISE NOTICE 'PASS: references and backend write restrictions';
END;
$test$;

RESET ROLE;

DO $deletion_test$
DECLARE
    rejected boolean := false;
BEGIN
    BEGIN
        DELETE FROM public.topics
        WHERE id = (
            SELECT topic_id FROM workflow_test_topics
            WHERE label = 'Workflow test A'
        );
    EXCEPTION
        WHEN foreign_key_violation THEN
            rejected := true;
    END;

    IF NOT rejected THEN
        RAISE EXCEPTION 'FAIL: a topic with a post could be deleted';
    END IF;

    RAISE NOTICE 'PASS: linked topic deletion is restricted';
END;
$deletion_test$;

ROLLBACK;