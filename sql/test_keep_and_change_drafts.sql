-- LOCAL/CI ONLY. All test data is rolled back.
BEGIN;

DO $tests$
DECLARE
    test_topic_id bigint;
    keep_post_id bigint;
    change_post_id bigint;
    waiting_post_id bigint;
    first_draft_id bigint;
    second_draft_id bigint;
    returned_draft_id bigint;
    returned_version integer;
    actual_status text;
    error_text text;
BEGIN
    -- Post for Skippa: one draft in draft_generated.
    INSERT INTO public.topics DEFAULT VALUES RETURNING id INTO test_topic_id;
    INSERT INTO public.posts (topic_id, status, kisslo_angle, telegram_chat_id)
    VALUES (test_topic_id, 'angle_received', 'Keep angle', -100123456789)
    RETURNING id INTO keep_post_id;
    SELECT result.draft_id INTO first_draft_id
    FROM public.save_post_draft(
        keep_post_id, 'Article', 'LinkedIn', '', ARRAY[]::bigint[], 'agree'
    ) AS result;

    -- Post for Ändra: one draft in draft_generated.
    INSERT INTO public.topics DEFAULT VALUES RETURNING id INTO test_topic_id;
    INSERT INTO public.posts (topic_id, status, kisslo_angle, telegram_chat_id)
    VALUES (test_topic_id, 'angle_received', 'Change angle', -100123456789)
    RETURNING id INTO change_post_id;
    SELECT result.draft_id INTO second_draft_id
    FROM public.save_post_draft(
        change_post_id, 'Article one', 'LinkedIn one', '',
        ARRAY[]::bigint[], 'agree'
    ) AS result;

    -- Post still waiting for a draft.
    INSERT INTO public.topics DEFAULT VALUES RETURNING id INTO test_topic_id;
    INSERT INTO public.posts (topic_id, status, kisslo_angle, telegram_chat_id)
    VALUES (test_topic_id, 'angle_received', 'Waiting angle', -100123456789)
    RETURNING id INTO waiting_post_id;

    -- Missing posts.
    error_text := NULL;
    BEGIN
        PERFORM public.keep_draft(-1, 1);
    EXCEPTION WHEN raise_exception THEN error_text := SQLERRM;
    END;
    IF error_text IS DISTINCT FROM 'Post -1 does not exist' THEN
        RAISE EXCEPTION 'FAIL: keep missing post: %', error_text;
    END IF;

    error_text := NULL;
    BEGIN
        PERFORM public.request_draft_changes(-1, 1, 'Shorter');
    EXCEPTION WHEN raise_exception THEN error_text := SQLERRM;
    END;
    IF error_text IS DISTINCT FROM 'Post -1 does not exist' THEN
        RAISE EXCEPTION 'FAIL: changes missing post: %', error_text;
    END IF;

    -- Wrong status.
    error_text := NULL;
    BEGIN
        PERFORM public.keep_draft(waiting_post_id, 1);
    EXCEPTION WHEN raise_exception THEN error_text := SQLERRM;
    END;
    IF error_text IS DISTINCT FROM format(
        'Post %s cannot be kept in status angle_received', waiting_post_id
    ) THEN
        RAISE EXCEPTION 'FAIL: keep wrong status: %', error_text;
    END IF;

    error_text := NULL;
    BEGIN
        PERFORM public.request_draft_changes(waiting_post_id, 1, 'Shorter');
    EXCEPTION WHEN raise_exception THEN error_text := SQLERRM;
    END;
    IF error_text IS DISTINCT FROM format(
        'Post %s cannot receive changes in status angle_received',
        waiting_post_id
    ) THEN
        RAISE EXCEPTION 'FAIL: changes wrong status: %', error_text;
    END IF;

    -- Old or unknown versions.
    error_text := NULL;
    BEGIN
        PERFORM public.keep_draft(keep_post_id, 2);
    EXCEPTION WHEN raise_exception THEN error_text := SQLERRM;
    END;
    IF error_text IS DISTINCT FROM format(
        'Post %s cannot be kept: version 2 is not the latest draft',
        keep_post_id
    ) THEN
        RAISE EXCEPTION 'FAIL: keep wrong version: %', error_text;
    END IF;

    error_text := NULL;
    BEGIN
        PERFORM public.request_draft_changes(change_post_id, 2, 'Shorter');
    EXCEPTION WHEN raise_exception THEN error_text := SQLERRM;
    END;
    IF error_text IS DISTINCT FROM format(
        'Post %s cannot receive changes: version 2 is not the latest draft',
        change_post_id
    ) THEN
        RAISE EXCEPTION 'FAIL: changes wrong version: %', error_text;
    END IF;

    -- An empty change request is rejected and nothing changes.
    error_text := NULL;
    BEGIN
        PERFORM public.request_draft_changes(change_post_id, 1, '   ');
    EXCEPTION WHEN raise_exception THEN error_text := SQLERRM;
    END;
    SELECT status INTO actual_status FROM public.posts WHERE id = change_post_id;
    IF error_text IS DISTINCT FROM format(
        'Post %s cannot receive changes: the change request is empty',
        change_post_id
    ) OR actual_status IS DISTINCT FROM 'draft_generated' THEN
        RAISE EXCEPTION 'FAIL: empty change request: %', error_text;
    END IF;

    -- Skippa keeps the latest draft.
    SELECT result.draft_id, result.version
    INTO returned_draft_id, returned_version
    FROM public.keep_draft(keep_post_id, 1) AS result;
    SELECT status INTO actual_status FROM public.posts WHERE id = keep_post_id;
    IF returned_draft_id IS DISTINCT FROM first_draft_id
       OR returned_version IS DISTINCT FROM 1
       OR actual_status IS DISTINCT FROM 'draft_kept' THEN
        RAISE EXCEPTION 'FAIL: keep latest draft';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM public.post_drafts WHERE id = first_draft_id) THEN
        RAISE EXCEPTION 'FAIL: kept draft was removed';
    END IF;

    -- A kept post cannot be kept again, changed or published.
    error_text := NULL;
    BEGIN
        PERFORM public.keep_draft(keep_post_id, 1);
    EXCEPTION WHEN raise_exception THEN error_text := SQLERRM;
    END;
    IF error_text IS DISTINCT FROM format(
        'Post %s cannot be kept in status draft_kept', keep_post_id
    ) THEN
        RAISE EXCEPTION 'FAIL: second keep: %', error_text;
    END IF;

    BEGIN
        PERFORM public.request_draft_changes(keep_post_id, 1, 'Shorter');
        RAISE EXCEPTION 'FAIL: kept post accepted changes';
    EXCEPTION WHEN raise_exception THEN
        IF SQLERRM LIKE 'FAIL:%' THEN RAISE; END IF;
    END;

    BEGIN
        PERFORM public.request_publish(keep_post_id, 1);
        RAISE EXCEPTION 'FAIL: kept post could be published';
    EXCEPTION WHEN raise_exception THEN
        IF SQLERRM LIKE 'FAIL:%' THEN RAISE; END IF;
    END;

    -- Ändra saves the request on the version Kisslo read.
    SELECT result.draft_id, result.version
    INTO returned_draft_id, returned_version
    FROM public.request_draft_changes(
        change_post_id, 1, 'Make it shorter'
    ) AS result;
    SELECT status INTO actual_status FROM public.posts WHERE id = change_post_id;
    IF returned_draft_id IS DISTINCT FROM second_draft_id
       OR returned_version IS DISTINCT FROM 1
       OR actual_status IS DISTINCT FROM 'changes_requested'
       OR NOT EXISTS (
           SELECT 1 FROM public.post_drafts
           WHERE id = second_draft_id AND change_request = 'Make it shorter'
       ) THEN
        RAISE EXCEPTION 'FAIL: change request was not saved';
    END IF;

    -- A second press before the new draft is rejected.
    error_text := NULL;
    BEGIN
        PERFORM public.request_draft_changes(change_post_id, 1, 'Again');
    EXCEPTION WHEN raise_exception THEN error_text := SQLERRM;
    END;
    IF error_text IS DISTINCT FROM format(
        'Post %s cannot receive changes in status changes_requested',
        change_post_id
    ) THEN
        RAISE EXCEPTION 'FAIL: second change request: %', error_text;
    END IF;

    -- save_post_draft saves version 2, which can then be published.
    SELECT result.version INTO returned_version
    FROM public.save_post_draft(
        change_post_id, 'Article two', 'LinkedIn two', '',
        ARRAY[]::bigint[], 'agree'
    ) AS result;
    SELECT status INTO actual_status FROM public.posts WHERE id = change_post_id;
    IF returned_version IS DISTINCT FROM 2
       OR actual_status IS DISTINCT FROM 'draft_generated' THEN
        RAISE EXCEPTION 'FAIL: next version after change request';
    END IF;
    IF EXISTS (
        SELECT 1 FROM public.post_drafts
        WHERE post_id = change_post_id AND version = 2
          AND change_request IS NOT NULL
    ) THEN
        RAISE EXCEPTION 'FAIL: new version inherited the change request';
    END IF;

    PERFORM public.request_publish(change_post_id, 2);

    RAISE NOTICE 'PASS: keep_draft, request_draft_changes, error texts and flow';
END;
$tests$;

DO $permissions_test$
DECLARE
    role_name text;
    function_name text;
BEGIN
    FOREACH function_name IN ARRAY ARRAY[
        'public.keep_draft(bigint,integer)',
        'public.request_draft_changes(bigint,integer,text)'
    ] LOOP
        IF NOT has_function_privilege('service_role', function_name, 'EXECUTE') THEN
            RAISE EXCEPTION 'FAIL: backend cannot call %', function_name;
        END IF;

        FOR role_name IN
            SELECT rolname FROM pg_roles WHERE rolname IN ('anon', 'authenticated')
        LOOP
            IF has_function_privilege(role_name, function_name, 'EXECUTE') THEN
                RAISE EXCEPTION 'FAIL: % can call %', role_name, function_name;
            END IF;
        END LOOP;
    END LOOP;

    IF has_column_privilege(
        'service_role', 'public.post_drafts', 'change_request', 'UPDATE'
    ) THEN
        RAISE EXCEPTION 'FAIL: backend can write change_request directly';
    END IF;

    RAISE NOTICE 'PASS: keep and change function permissions';
END;
$permissions_test$;

-- Run both functions as the real backend role.
CREATE TEMP TABLE keep_change_backend_context (
    keep_post_id bigint NOT NULL,
    change_post_id bigint NOT NULL
) ON COMMIT DROP;

DO $fixture$
DECLARE
    new_topic_id bigint;
    first_post_id bigint;
    second_post_id bigint;
BEGIN
    INSERT INTO public.topics DEFAULT VALUES RETURNING id INTO new_topic_id;
    INSERT INTO public.posts (topic_id, status, kisslo_angle, telegram_chat_id)
    VALUES (new_topic_id, 'angle_received', 'Backend keep', -100123456790)
    RETURNING id INTO first_post_id;
    PERFORM public.save_post_draft(
        first_post_id, 'Article', 'LinkedIn', '', ARRAY[]::bigint[], 'agree'
    );

    INSERT INTO public.topics DEFAULT VALUES RETURNING id INTO new_topic_id;
    INSERT INTO public.posts (topic_id, status, kisslo_angle, telegram_chat_id)
    VALUES (new_topic_id, 'angle_received', 'Backend change', -100123456790)
    RETURNING id INTO second_post_id;
    PERFORM public.save_post_draft(
        second_post_id, 'Article', 'LinkedIn', '', ARRAY[]::bigint[], 'agree'
    );

    INSERT INTO pg_temp.keep_change_backend_context
    VALUES (first_post_id, second_post_id);
END;
$fixture$;

GRANT SELECT ON pg_temp.keep_change_backend_context TO service_role;

SET LOCAL ROLE service_role;

DO $backend_test$
DECLARE
    first_post_id bigint;
    second_post_id bigint;
BEGIN
    SELECT keep_post_id, change_post_id
    INTO STRICT first_post_id, second_post_id
    FROM pg_temp.keep_change_backend_context;

    PERFORM public.keep_draft(first_post_id, 1);
    PERFORM public.request_draft_changes(second_post_id, 1, 'Backend change');

    IF NOT EXISTS (
        SELECT 1 FROM public.posts WHERE id = first_post_id AND status = 'draft_kept'
    ) OR NOT EXISTS (
        SELECT 1 FROM public.posts
        WHERE id = second_post_id AND status = 'changes_requested'
    ) OR NOT EXISTS (
        SELECT 1 FROM public.post_drafts
        WHERE post_id = second_post_id AND change_request = 'Backend change'
    ) THEN
        RAISE EXCEPTION 'FAIL: backend cannot verify keep and change';
    END IF;

    RAISE NOTICE 'PASS: service_role kept a draft and requested changes';
END;
$backend_test$;

RESET ROLE;

ROLLBACK;
