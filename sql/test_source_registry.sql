-- Local/CI test. All test records are rolled back.

BEGIN;

DO $tests$
DECLARE
    invalid_type text;
    role_name text;
BEGIN
    -- Unclassified sources are allowed.
    INSERT INTO public.source_registry (
        source_normalized, name
    )
    VALUES ('__registry_test__', 'Registry Test');

    -- Both agreed categories must work.
    UPDATE public.source_registry
    SET source_type = 'media'
    WHERE source_normalized = '__registry_test__';

    UPDATE public.source_registry
    SET source_type = 'authority'
    WHERE source_normalized = '__registry_test__';

    -- Duplicate source keys must fail.
    BEGIN
        INSERT INTO public.source_registry (
            source_normalized, name
        )
        VALUES ('__registry_test__', 'Duplicate');

        RAISE EXCEPTION 'FAIL: duplicate source key accepted';
    EXCEPTION
        WHEN unique_violation THEN NULL;
    END;

    -- Blank source keys must fail.
    BEGIN
        INSERT INTO public.source_registry (
            source_normalized, name
        )
        VALUES ('   ', 'Blank Key');

        RAISE EXCEPTION 'FAIL: blank source key accepted';
    EXCEPTION
        WHEN check_violation THEN NULL;
    END;

    -- Blank display names must fail.
    BEGIN
        UPDATE public.source_registry
        SET name = E' \t\n'
        WHERE source_normalized = '__registry_test__';

        RAISE EXCEPTION 'FAIL: blank display name accepted';
    EXCEPTION
        WHEN check_violation THEN NULL;
    END;

    -- Categories outside the agreed values must fail.
    FOREACH invalid_type IN ARRAY ARRAY[
        '',
        E' \t\n',
        'test_category',
        'MEDIA',
        'government',
        ' authority '
    ]
    LOOP
        BEGIN
            UPDATE public.source_registry
            SET source_type = invalid_type
            WHERE source_normalized = '__registry_test__';

            RAISE EXCEPTION
                'FAIL: invalid category accepted: %', invalid_type;
        EXCEPTION
            WHEN check_violation THEN NULL;
        END;
    END LOOP;

    -- A source can return to unclassified.
    UPDATE public.source_registry
    SET source_type = NULL
    WHERE source_normalized = '__registry_test__';

    -- Per-source weights must not be stored here.
    IF EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'source_registry'
          AND column_name = 'authority_weight'
    ) THEN
        RAISE EXCEPTION 'FAIL: authority_weight column still exists';
    END IF;

    -- RLS must be enabled.
    IF NOT (
        SELECT relrowsecurity
        FROM pg_class
        WHERE oid = 'public.source_registry'::regclass
    ) THEN
        RAISE EXCEPTION 'FAIL: RLS is disabled';
    END IF;

    -- Check effective application-role permissions.
    FOR role_name IN
        SELECT rolname
        FROM pg_roles
        WHERE rolname IN ('anon', 'authenticated', 'service_role')
    LOOP
        IF has_table_privilege(
            role_name,
            'public.source_registry',
            'INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER'
        ) THEN
            RAISE EXCEPTION
                'FAIL: % has unexpected write privileges', role_name;
        END IF;

        IF has_table_privilege(
            role_name, 'public.source_registry', 'SELECT'
        ) IS DISTINCT FROM (role_name = 'service_role') THEN
            RAISE EXCEPTION
                'FAIL: unexpected SELECT permission for %', role_name;
        END IF;
    END LOOP;

    RAISE NOTICE 'PASS: source registry assertions passed';
END;
$tests$;

ROLLBACK;