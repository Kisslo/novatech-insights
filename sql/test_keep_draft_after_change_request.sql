-- LOCAL/CI ONLY. All test data is rolled back.
BEGIN;

DO $tests$
DECLARE
    test_topic_id bigint;
    test_post_id bigint;
    first_draft_id bigint;
    returned_draft_id bigint;
    returned_version integer;
    actual_status text;
    error_text text;
BEGIN
    INSERT INTO public.topics DEFAULT VALUES RETURNING id INTO test_topic_id;
    INSERT INTO public.posts (topic_id, status, kisslo_angle, telegram_chat_id)
    VALUES (test_topic_id, 'angle_received', 'Test angle', -100123456789)
    RETURNING id INTO test_post_id;
    SELECT result.draft_id INTO first_draft_id
    FROM public.save_post_draft(
        test_post_id, 'Article', 'LinkedIn', '', ARRAY[]::bigint[], 'agree'
    ) AS result;

    -- Ändra saves the request, then writing the new version fails.
    PERFORM public.request_draft_changes(test_post_id, 1, 'Shorter');

    -- Publicera is still refused in changes_requested.
    error_text := NULL;
    BEGIN
        PERFORM public.request_publish(test_post_id, 1);
    EXCEPTION WHEN raise_exception THEN error_text := SQLERRM;
    END;
    IF error_text IS DISTINCT FROM format(
        'Post %s cannot be published in status changes_requested',
        test_post_id
    ) THEN
        RAISE EXCEPTION 'FAIL: publish after change request: %', error_text;
    END IF;

    -- An old or unknown version is refused, and nothing changes.
    error_text := NULL;
    BEGIN
        PERFORM public.keep_draft(test_post_id, 2);
    EXCEPTION WHEN raise_exception THEN error_text := SQLERRM;
    END;
    SELECT status INTO actual_status FROM public.posts WHERE id = test_post_id;
    IF error_text IS DISTINCT FROM format(
        'Post %s cannot be kept: version 2 is not the latest draft',
        test_post_id
    ) OR actual_status IS DISTINCT FROM 'changes_requested' THEN
        RAISE EXCEPTION 'FAIL: keep wrong version: %', error_text;
    END IF;

    -- Skippa now works from changes_requested.
    SELECT result.draft_id, result.version
    INTO returned_draft_id, returned_version
    FROM public.keep_draft(test_post_id, 1) AS result;
    SELECT status INTO actual_status FROM public.posts WHERE id = test_post_id;
    IF returned_draft_id IS DISTINCT FROM first_draft_id
       OR returned_version IS DISTINCT FROM 1
       OR actual_status IS DISTINCT FROM 'draft_kept' THEN
        RAISE EXCEPTION 'FAIL: keep from changes_requested';
    END IF;

    -- The saved change request stays on the version.
    IF NOT EXISTS (
        SELECT 1 FROM public.post_drafts
        WHERE id = first_draft_id AND change_request = 'Shorter'
    ) THEN
        RAISE EXCEPTION 'FAIL: change request was lost';
    END IF;

    -- A kept post cannot get a new draft or be kept again.
    BEGIN
        PERFORM public.save_post_draft(
            test_post_id, 'Article two', 'LinkedIn two', '',
            ARRAY[]::bigint[], 'agree'
        );
        RAISE EXCEPTION 'FAIL: kept post accepted a new draft';
    EXCEPTION WHEN raise_exception THEN
        IF SQLERRM LIKE 'FAIL:%' THEN RAISE; END IF;
    END;

    error_text := NULL;
    BEGIN
        PERFORM public.keep_draft(test_post_id, 1);
    EXCEPTION WHEN raise_exception THEN error_text := SQLERRM;
    END;
    IF error_text IS DISTINCT FROM format(
        'Post %s cannot be kept in status draft_kept', test_post_id
    ) THEN
        RAISE EXCEPTION 'FAIL: second keep: %', error_text;
    END IF;

    RAISE NOTICE 'PASS: keep_draft from changes_requested';
END;
$tests$;

DO $permissions_test$
DECLARE
    role_name text;
BEGIN
    IF NOT has_function_privilege(
        'service_role', 'public.keep_draft(bigint,integer)', 'EXECUTE'
    ) THEN
        RAISE EXCEPTION 'FAIL: backend cannot call keep_draft';
    END IF;

    FOR role_name IN
        SELECT rolname FROM pg_roles WHERE rolname IN ('anon', 'authenticated')
    LOOP
        IF has_function_privilege(
            role_name, 'public.keep_draft(bigint,integer)', 'EXECUTE'
        ) THEN
            RAISE EXCEPTION 'FAIL: % can call keep_draft', role_name;
        END IF;
    END LOOP;

    RAISE NOTICE 'PASS: keep_draft permissions after 015';
END;
$permissions_test$;

ROLLBACK;
