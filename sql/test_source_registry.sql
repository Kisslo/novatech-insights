-- Local/CI test. All test records are rolled back.

BEGIN;

DO $tests$
DECLARE
    invalid_weight double precision;
    role_name text;
BEGIN
    -- Unclassified sources are allowed.
    INSERT INTO public.source_registry (
        source_normalized, name
    )
    VALUES ('__registry_test__', 'Registry Test');

    -- Zero and positive weights are allowed.
    UPDATE public.source_registry
    SET authority_weight = 0
    WHERE source_normalized = '__registry_test__';

    UPDATE public.source_registry
    SET source_type = 'test_category',
        authority_weight = 1.5
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

    -- Blank categories must fail.
    BEGIN
        UPDATE public.source_registry
        SET source_type = E' \t\n'
        WHERE source_normalized = '__registry_test__';

        RAISE EXCEPTION 'FAIL: blank category accepted';
    EXCEPTION
        WHEN check_violation THEN NULL;
    END;

    -- Negative and non-finite weights must fail.
    FOREACH invalid_weight IN ARRAY ARRAY[
        -1::double precision,
        'NaN'::double precision,
        'Infinity'::double precision,
        '-Infinity'::double precision
    ]
    LOOP
        BEGIN
            UPDATE public.source_registry
            SET authority_weight = invalid_weight
            WHERE source_normalized = '__registry_test__';

            RAISE EXCEPTION
                'FAIL: invalid weight accepted: %', invalid_weight;
        EXCEPTION
            WHEN check_violation THEN NULL;
        END;
    END LOOP;

    -- Unassigned values remain allowed.
    UPDATE public.source_registry
    SET source_type = NULL,
        authority_weight = NULL
    WHERE source_normalized = '__registry_test__';

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