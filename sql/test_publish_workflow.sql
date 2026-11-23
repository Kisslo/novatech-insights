-- LOCAL/CI ONLY. All test data is rolled back.
BEGIN;

DO $tests$
DECLARE
    test_topic_id bigint;
    test_post_id bigint;
    other_post_id bigint;
    first_draft_id bigint;
    second_draft_id bigint;
    returned_draft_id bigint;
    returned_version integer;
    actual_status text;
    error_text text;
    missing_post_id bigint := -1;
BEGIN
    -- A post with two draft versions in draft_generated.
    INSERT INTO public.topics DEFAULT VALUES
    RETURNING id INTO test_topic_id;

    INSERT INTO public.posts (
        topic_id, status, kisslo_angle, telegram_chat_id
    )
    VALUES (test_topic_id, 'angle_received', 'Test angle', -100123456789)
    RETURNING id INTO test_post_id;

    SELECT result.draft_id INTO first_draft_id
    FROM public.save_post_draft(
        test_post_id, 'Article one', 'LinkedIn one', '',
        ARRAY[]::bigint[], 'agree'
    ) AS result;

    UPDATE public.posts SET status = 'changes_requested'
    WHERE id = test_post_id;

    SELECT result.draft_id INTO second_draft_id
    FROM public.save_post_draft(
        test_post_id, 'Article two', 'LinkedIn two', '',
        ARRAY[]::bigint[], 'agree'
    ) AS result;

    -- A second post that is still waiting for a draft.
    INSERT INTO public.topics DEFAULT VALUES
    RETURNING id INTO test_topic_id;

    INSERT INTO public.posts (
        topic_id, status, kisslo_angle, telegram_chat_id
    )
    VALUES (test_topic_id, 'angle_received', 'Other angle', -100123456789)
    RETURNING id INTO other_post_id;

    -- Missing posts are rejected by all three functions.
    error_text := NULL;
    BEGIN
        PERFORM public.request_publish(missing_post_id, 1);
    EXCEPTION WHEN raise_exception THEN
        error_text := SQLERRM;
    END;
    IF error_text IS DISTINCT FROM 'Post -1 does not exist' THEN
        RAISE EXCEPTION 'FAIL: request_publish missing post: %', error_text;
    END IF;

    error_text := NULL;
    BEGIN
        PERFORM public.mark_post_published(
            missing_post_id, 1, 1, 'https://example.com/a'
        );
    EXCEPTION WHEN raise_exception THEN
        error_text := SQLERRM;
    END;
    IF error_text IS DISTINCT FROM 'Post -1 does not exist' THEN
        RAISE EXCEPTION 'FAIL: mark_post_published missing post: %', error_text;
    END IF;

    error_text := NULL;
    BEGIN
        PERFORM public.cancel_publish_request(missing_post_id);
    EXCEPTION WHEN raise_exception THEN
        error_text := SQLERRM;
    END;
    IF error_text IS DISTINCT FROM 'Post -1 does not exist' THEN
        RAISE EXCEPTION 'FAIL: cancel missing post: %', error_text;
    END IF;

    -- A post without a generated draft cannot be published.
    error_text := NULL;
    BEGIN
        PERFORM public.request_publish(other_post_id, 1);
    EXCEPTION WHEN raise_exception THEN
        error_text := SQLERRM;
    END;
    IF error_text IS DISTINCT FROM format(
        'Post %s cannot be published in status angle_received',
        other_post_id
    ) THEN
        RAISE EXCEPTION 'FAIL: wrong-status request: %', error_text;
    END IF;

    -- An old version is rejected and the status is unchanged.
    error_text := NULL;
    BEGIN
        PERFORM public.request_publish(test_post_id, 1);
    EXCEPTION WHEN raise_exception THEN
        error_text := SQLERRM;
    END;
    SELECT status INTO actual_status
    FROM public.posts WHERE id = test_post_id;
    IF error_text IS DISTINCT FROM format(
        'Post %s cannot be published: version 1 is not the latest draft',
        test_post_id
    ) OR actual_status IS DISTINCT FROM 'draft_generated' THEN
        RAISE EXCEPTION 'FAIL: old version request: %', error_text;
    END IF;

    -- The latest version is accepted and returned.
    SELECT result.draft_id, result.version
    INTO returned_draft_id, returned_version
    FROM public.request_publish(test_post_id, 2) AS result;
    SELECT status INTO actual_status
    FROM public.posts WHERE id = test_post_id;
    IF returned_draft_id IS DISTINCT FROM second_draft_id
       OR returned_version IS DISTINCT FROM 2
       OR actual_status IS DISTINCT FROM 'publish_requested' THEN
        RAISE EXCEPTION 'FAIL: latest version request';
    END IF;

    -- A repeated request is rejected.
    error_text := NULL;
    BEGIN
        PERFORM public.request_publish(test_post_id, 2);
    EXCEPTION WHEN raise_exception THEN
        error_text := SQLERRM;
    END;
    IF error_text IS DISTINCT FROM format(
        'Post %s cannot be published in status publish_requested',
        test_post_id
    ) THEN
        RAISE EXCEPTION 'FAIL: repeated request: %', error_text;
    END IF;

    -- Cancel returns to draft_generated, and only works once.
    PERFORM public.cancel_publish_request(test_post_id);
    SELECT status INTO actual_status
    FROM public.posts WHERE id = test_post_id;
    IF actual_status IS DISTINCT FROM 'draft_generated' THEN
        RAISE EXCEPTION 'FAIL: cancel status';
    END IF;

    error_text := NULL;
    BEGIN
        PERFORM public.cancel_publish_request(test_post_id);
    EXCEPTION WHEN raise_exception THEN
        error_text := SQLERRM;
    END;
    IF error_text IS DISTINCT FROM format(
        'Post %s cannot cancel publishing in status draft_generated',
        test_post_id
    ) THEN
        RAISE EXCEPTION 'FAIL: repeated cancel: %', error_text;
    END IF;

    -- Marking published requires publish_requested.
    error_text := NULL;
    BEGIN
        PERFORM public.mark_post_published(
            test_post_id, second_draft_id, 101, 'https://example.com/a'
        );
    EXCEPTION WHEN raise_exception THEN
        error_text := SQLERRM;
    END;
    IF error_text IS DISTINCT FROM format(
        'Post %s cannot be marked published in status draft_generated',
        test_post_id
    ) THEN
        RAISE EXCEPTION 'FAIL: mark before request: %', error_text;
    END IF;

    PERFORM public.request_publish(test_post_id, 2);

    -- An older draft cannot be marked as the published one.
    error_text := NULL;
    BEGIN
        PERFORM public.mark_post_published(
            test_post_id, first_draft_id, 101, 'https://example.com/a'
        );
    EXCEPTION WHEN raise_exception THEN
        error_text := SQLERRM;
    END;
    IF error_text IS DISTINCT FROM format(
        'Post %s cannot be marked published: draft %s is not the latest draft',
        test_post_id, first_draft_id
    ) THEN
        RAISE EXCEPTION 'FAIL: old draft marked: %', error_text;
    END IF;

    -- Invalid WordPress details are rejected.
    BEGIN
        PERFORM public.mark_post_published(
            test_post_id, second_draft_id, 101, 'not a url'
        );
        RAISE EXCEPTION 'FAIL: invalid URL accepted';
    EXCEPTION WHEN check_violation THEN
        NULL;
    END;

    -- A valid mark stores every detail.
    PERFORM public.mark_post_published(
        test_post_id, second_draft_id, 101, 'https://example.com/a'
    );
    IF NOT EXISTS (
        SELECT 1 FROM public.posts
        WHERE id = test_post_id
          AND status = 'published'
          AND approved_draft_id = second_draft_id
          AND wordpress_post_id = 101
          AND published_url = 'https://example.com/a'
          AND published_at IS NOT NULL
    ) THEN
        RAISE EXCEPTION 'FAIL: published details were not saved';
    END IF;

    -- A published post can never be published or cancelled again.
    error_text := NULL;
    BEGIN
        PERFORM public.mark_post_published(
            test_post_id, second_draft_id, 102, 'https://example.com/b'
        );
    EXCEPTION WHEN raise_exception THEN
        error_text := SQLERRM;
    END;
    IF error_text IS DISTINCT FROM format(
        'Post %s cannot be marked published in status published',
        test_post_id
    ) THEN
        RAISE EXCEPTION 'FAIL: second mark: %', error_text;
    END IF;

    error_text := NULL;
    BEGIN
        PERFORM public.request_publish(test_post_id, 2);
    EXCEPTION WHEN raise_exception THEN
        error_text := SQLERRM;
    END;
    IF error_text IS DISTINCT FROM format(
        'Post %s cannot be published in status published',
        test_post_id
    ) THEN
        RAISE EXCEPTION 'FAIL: request after publish: %', error_text;
    END IF;

    -- A published post cannot be moved back by a direct update.
    BEGIN
        UPDATE public.posts SET status = 'draft_generated'
        WHERE id = test_post_id;
        RAISE EXCEPTION 'FAIL: published post was moved back';
    EXCEPTION WHEN check_violation THEN
        NULL;
    END;

    -- A post cannot be set to published without its details.
    BEGIN
        UPDATE public.posts SET status = 'published'
        WHERE id = other_post_id;
        RAISE EXCEPTION 'FAIL: published without details';
    EXCEPTION WHEN check_violation THEN
        NULL;
    END;

    -- draft_kept (Skippa) is an allowed status.
    UPDATE public.posts SET status = 'draft_kept'
    WHERE id = other_post_id;

    -- A change request must not be blank.
    UPDATE public.post_drafts SET change_request = 'Shorter, please'
    WHERE id = first_draft_id;

    BEGIN
        UPDATE public.post_drafts SET change_request = '   '
        WHERE id = first_draft_id;
        RAISE EXCEPTION 'FAIL: blank change request accepted';
    EXCEPTION WHEN check_violation THEN
        NULL;
    END;

    RAISE NOTICE
        'PASS: publish requests, cancel, mark published, error texts and constraints';
END;
$tests$;

DO $permissions_test$
DECLARE
    role_name text;
    function_name text;
    function_names text[] := ARRAY[
        'public.request_publish(bigint,integer)',
        'public.mark_post_published(bigint,bigint,bigint,text)',
        'public.cancel_publish_request(bigint)'
    ];
BEGIN
    FOREACH function_name IN ARRAY function_names LOOP
        IF NOT has_function_privilege(
            'service_role', function_name, 'EXECUTE'
        ) THEN
            RAISE EXCEPTION 'FAIL: backend cannot call %', function_name;
        END IF;

        FOR role_name IN
            SELECT rolname FROM pg_roles
            WHERE rolname IN ('anon', 'authenticated')
        LOOP
            IF has_function_privilege(role_name, function_name, 'EXECUTE') THEN
                RAISE EXCEPTION
                    'FAIL: % can call %', role_name, function_name;
            END IF;
        END LOOP;
    END LOOP;

    IF NOT has_column_privilege(
        'service_role', 'public.posts', 'published_url', 'SELECT'
    ) OR NOT has_column_privilege(
        'service_role', 'public.post_drafts', 'change_request', 'SELECT'
    ) THEN
        RAISE EXCEPTION 'FAIL: backend cannot read new columns';
    END IF;

    IF has_column_privilege(
        'service_role', 'public.posts', 'wordpress_post_id', 'UPDATE'
    ) OR has_column_privilege(
        'service_role', 'public.posts', 'published_url', 'UPDATE'
    ) THEN
        RAISE EXCEPTION 'FAIL: backend can write publish details directly';
    END IF;

    RAISE NOTICE 'PASS: publishing function and column permissions';
END;
$permissions_test$;

-- Prepare a post for the real backend-role test.
CREATE TEMP TABLE publish_backend_test_context (
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
    VALUES (new_topic_id, 'angle_received', 'Backend angle', -100123456790)
    RETURNING id INTO new_post_id;

    PERFORM public.save_post_draft(
        new_post_id, 'Backend article', 'Backend LinkedIn', '',
        ARRAY[]::bigint[], 'agree'
    );

    INSERT INTO pg_temp.publish_backend_test_context (post_id)
    VALUES (new_post_id);
END;
$fixture$;

GRANT SELECT ON pg_temp.publish_backend_test_context
TO service_role;

SET LOCAL ROLE service_role;

DO $backend_test$
DECLARE
    test_post_id bigint;
    returned_draft_id bigint;
    returned_version integer;
BEGIN
    IF current_user <> 'service_role' THEN
        RAISE EXCEPTION 'FAIL: test is not running as service_role';
    END IF;

    SELECT post_id INTO STRICT test_post_id
    FROM pg_temp.publish_backend_test_context;

    SELECT result.draft_id, result.version
    INTO STRICT returned_draft_id, returned_version
    FROM public.request_publish(test_post_id, 1) AS result;

    PERFORM public.mark_post_published(
        test_post_id, returned_draft_id, 201,
        'https://example.com/backend'
    );

    IF NOT EXISTS (
        SELECT 1 FROM public.posts
        WHERE id = test_post_id
          AND status = 'published'
          AND approved_draft_id = returned_draft_id
          AND wordpress_post_id = 201
          AND published_url = 'https://example.com/backend'
          AND published_at IS NOT NULL
    ) THEN
        RAISE EXCEPTION 'FAIL: backend cannot verify published post';
    END IF;

    RAISE NOTICE 'PASS: service_role requested and marked a publication';
END;
$backend_test$;

RESET ROLE;

ROLLBACK;
