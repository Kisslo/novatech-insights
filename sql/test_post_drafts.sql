-- LOCAL/CI ONLY. All test data is rolled back.
BEGIN;

DO $tests$
DECLARE
    test_topic_id bigint;
    test_post_id bigint;
    saved_id bigint;
    saved_version integer;
    actual_status text;
    draft_count bigint;
    blocked boolean;
BEGIN
    INSERT INTO public.topics DEFAULT VALUES
    RETURNING id INTO test_topic_id;

    INSERT INTO public.posts (
        topic_id, status, kisslo_angle, telegram_chat_id
    )
    VALUES (
        test_topic_id, 'awaiting_angle', NULL, -100123456789
    )
    RETURNING id INTO test_post_id;

    -- Saving before an angle is received must fail.
    blocked := false;
    BEGIN
        PERFORM public.save_post_draft(
            test_post_id, 'Article', 'LinkedIn', '',
            ARRAY[]::bigint[], 'agree'
        );
    EXCEPTION WHEN raise_exception THEN
        blocked := true;
    END;

    IF NOT blocked THEN
        RAISE EXCEPTION 'FAIL: draft accepted before angle';
    END IF;

    UPDATE public.posts
    SET status = 'angle_received', kisslo_angle = 'Test angle'
    WHERE id = test_post_id;

    -- First save returns version 1 and changes status.
    SELECT result.draft_id, result.version
    INTO saved_id, saved_version
    FROM public.save_post_draft(
        test_post_id, 'Article one', 'LinkedIn one',
        'Reviewer notes', ARRAY[]::bigint[], 'agree'
    ) AS result;

    SELECT status INTO actual_status
    FROM public.posts WHERE id = test_post_id;

    IF saved_id IS NULL OR saved_version IS DISTINCT FROM 1
       OR actual_status IS DISTINCT FROM 'draft_generated' THEN
        RAISE EXCEPTION 'FAIL: first save or status update';
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM public.post_drafts
        WHERE id = saved_id
          AND post_id = test_post_id
          AND article_text = 'Article one'
          AND linkedin_text = 'LinkedIn one'
          AND reviewer_notes = 'Reviewer notes'
          AND source_news_ids = ARRAY[]::bigint[]
          AND stance = 'agree'
    ) THEN
        RAISE EXCEPTION 'FAIL: saved content differs';
    END IF;

    -- Saving from draft_generated creates version 2.
    SELECT result.version INTO saved_version
    FROM public.save_post_draft(
        test_post_id, 'Article two', 'LinkedIn two', '',
        ARRAY[]::bigint[], 'rebut'
    ) AS result;

    IF saved_version IS DISTINCT FROM 2 THEN
        RAISE EXCEPTION 'FAIL: second version';
    END IF;

    -- Invalid content must preserve both status and drafts.
    UPDATE public.posts SET status = 'changes_requested'
    WHERE id = test_post_id;

    blocked := false;
    BEGIN
        PERFORM public.save_post_draft(
            test_post_id, ' ', 'LinkedIn', '',
            ARRAY[]::bigint[], 'agree'
        );
    EXCEPTION WHEN check_violation THEN
        blocked := true;
    END;

    SELECT status INTO actual_status
    FROM public.posts WHERE id = test_post_id;

    SELECT COUNT(*) INTO draft_count
    FROM public.post_drafts WHERE post_id = test_post_id;

    IF NOT blocked OR draft_count <> 2
       OR actual_status IS DISTINCT FROM 'changes_requested' THEN
        RAISE EXCEPTION 'FAIL: invalid save changed data';
    END IF;

    -- A valid replacement after changes_requested is version 3.
    SELECT result.version INTO saved_version
    FROM public.save_post_draft(
        test_post_id, 'Article three', 'LinkedIn three', '',
        ARRAY[]::bigint[], 'agree'
    ) AS result;

    IF saved_version IS DISTINCT FROM 3 THEN
        RAISE EXCEPTION 'FAIL: changes_requested save';
    END IF;

    -- Approved content must not receive a new draft.
    UPDATE public.posts SET status = 'approved'
    WHERE id = test_post_id;

    blocked := false;
    BEGIN
        PERFORM public.save_post_draft(
            test_post_id, 'Article', 'LinkedIn', '',
            ARRAY[]::bigint[], 'agree'
        );
    EXCEPTION WHEN raise_exception THEN
        blocked := true;
    END;

    SELECT COUNT(*) INTO draft_count
    FROM public.post_drafts WHERE post_id = test_post_id;

    IF NOT blocked OR draft_count <> 3 THEN
        RAISE EXCEPTION 'FAIL: approved post accepted draft';
    END IF;

    RAISE NOTICE
        'PASS: draft versions, saved content, status guards and failed-save rollback';
END;
$tests$;
DO $permissions_test$
DECLARE
    role_name text;
    function_name text :=
        'public.save_post_draft(bigint,text,text,text,bigint[],text)';
BEGIN
    IF NOT (
        SELECT relrowsecurity
        FROM pg_class
        WHERE oid = 'public.post_drafts'::regclass
    ) THEN
        RAISE EXCEPTION 'FAIL: draft RLS is disabled';
    END IF;

    IF NOT has_table_privilege(
        'service_role', 'public.post_drafts', 'SELECT'
    ) THEN
        RAISE EXCEPTION 'FAIL: backend cannot read drafts';
    END IF;

    IF has_table_privilege(
        'service_role', 'public.post_drafts', 'INSERT,UPDATE,DELETE'
    ) THEN
        RAISE EXCEPTION 'FAIL: backend has direct draft writes';
    END IF;

    IF NOT has_function_privilege(
        'service_role', function_name, 'EXECUTE'
    ) THEN
        RAISE EXCEPTION 'FAIL: backend cannot call draft function';
    END IF;

    FOR role_name IN
        SELECT rolname FROM pg_roles
        WHERE rolname IN ('anon', 'authenticated')
    LOOP
        IF has_table_privilege(
            role_name, 'public.post_drafts',
            'SELECT,INSERT,UPDATE,DELETE'
        ) OR has_function_privilege(
            role_name, function_name, 'EXECUTE'
        ) THEN
            RAISE EXCEPTION
                'FAIL: unexpected draft access for %', role_name;
        END IF;
    END LOOP;

    RAISE NOTICE 'PASS: draft RLS and backend permissions';
END;
$permissions_test$;

-- Prepare a post for the real backend-role test.
CREATE TEMP TABLE draft_backend_test_context (
    post_id bigint NOT NULL
) ON COMMIT DROP;

DO $fixture$
DECLARE
    new_topic_id bigint;
    new_post_id bigint;
BEGIN
    INSERT INTO public.topics DEFAULT VALUES
    RETURNING id INTO new_topic_id;

    INSERT INTO public.posts (
        topic_id, status, kisslo_angle, telegram_chat_id
    )
    VALUES (
        new_topic_id,
        'angle_received',
        'Backend role test angle',
        -100123456790
    )
    RETURNING id INTO new_post_id;

    INSERT INTO pg_temp.draft_backend_test_context (post_id)
    VALUES (new_post_id);
END;
$fixture$;

GRANT SELECT ON pg_temp.draft_backend_test_context
TO service_role;

SET LOCAL ROLE service_role;

DO $backend_test$
DECLARE
    test_post_id bigint;
    saved_id bigint;
    saved_version integer;
BEGIN
    IF current_user <> 'service_role' THEN
        RAISE EXCEPTION 'FAIL: test is not running as service_role';
    END IF;

    SELECT post_id INTO STRICT test_post_id
    FROM pg_temp.draft_backend_test_context;

    SELECT result.draft_id, result.version
    INTO STRICT saved_id, saved_version
    FROM public.save_post_draft(
        test_post_id,
        'Backend test article',
        'Backend test LinkedIn',
        'Private reviewer notes',
        ARRAY[]::bigint[],
        'agree'
    ) AS result;

    IF saved_id IS NULL OR saved_version IS DISTINCT FROM 1 THEN
        RAISE EXCEPTION 'FAIL: backend draft result';
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM public.post_drafts
        WHERE id = saved_id
          AND post_id = test_post_id
          AND version = saved_version
          AND article_text = 'Backend test article'
          AND linkedin_text = 'Backend test LinkedIn'
          AND reviewer_notes = 'Private reviewer notes'
          AND source_news_ids = ARRAY[]::bigint[]
          AND stance = 'agree'
    ) THEN
        RAISE EXCEPTION 'FAIL: backend cannot verify saved draft';
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM public.posts
        WHERE id = test_post_id
          AND status = 'draft_generated'
          AND kisslo_angle = 'Backend role test angle'
    ) THEN
        RAISE EXCEPTION 'FAIL: backend cannot verify post status';
    END IF;

    RAISE NOTICE
        'PASS: service_role saved a draft and verified content and status';
END;
$backend_test$;

RESET ROLE;

ROLLBACK;