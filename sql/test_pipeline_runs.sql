-- Local/CI test only. Never run in shared Supabase.
\set ON_ERROR_STOP on

BEGIN;

DO $test$
BEGIN
    IF to_regclass('public.pipeline_runs') IS NULL THEN
        RAISE EXCEPTION 'FAIL: pipeline_runs table is missing';
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_class
        WHERE oid = 'public.pipeline_runs'::regclass
          AND relrowsecurity
    ) THEN
        RAISE EXCEPTION 'FAIL: pipeline_runs RLS is not enabled';
    END IF;

    IF has_table_privilege('service_role', 'public.pipeline_runs', 'DELETE') THEN
        RAISE EXCEPTION 'FAIL: service_role can delete pipeline runs';
    END IF;

    IF EXISTS (
        SELECT 1 FROM pg_roles WHERE rolname = 'anon'
    ) AND (
        has_table_privilege('anon', 'public.pipeline_runs', 'SELECT')
        OR has_table_privilege('anon', 'public.pipeline_runs', 'INSERT')
        OR has_table_privilege('anon', 'public.pipeline_runs', 'UPDATE')
        OR has_table_privilege('anon', 'public.pipeline_runs', 'DELETE')
    ) THEN
        RAISE EXCEPTION 'FAIL: anon has pipeline run privileges';
    END IF;

    IF EXISTS (
        SELECT 1 FROM pg_roles WHERE rolname = 'authenticated'
    ) AND (
        has_table_privilege(
            'authenticated', 'public.pipeline_runs', 'SELECT'
        )
        OR has_table_privilege(
            'authenticated', 'public.pipeline_runs', 'INSERT'
        )
        OR has_table_privilege(
            'authenticated', 'public.pipeline_runs', 'UPDATE'
        )
        OR has_table_privilege(
            'authenticated', 'public.pipeline_runs', 'DELETE'
        )
    ) THEN
        RAISE EXCEPTION 'FAIL: authenticated has pipeline run privileges';
    END IF;
END;
$test$;

SET LOCAL ROLE service_role;

INSERT INTO public.pipeline_runs (
    run_id, stage, mode, status, started_at
)
VALUES (
    '00000000-0000-0000-0000-000000000001',
    'ranking',
    'read_only',
    'running',
    now()
);

DO $select$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM public.pipeline_runs
        WHERE run_id = '00000000-0000-0000-0000-000000000001'::uuid
    ) THEN
        RAISE EXCEPTION 'FAIL: service_role could not select pipeline run';
    END IF;
END;
$select$;

UPDATE public.pipeline_runs
SET status = 'success', finished_at = now()
WHERE run_id = '00000000-0000-0000-0000-000000000001'::uuid;

DO $update$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM public.pipeline_runs
        WHERE run_id = '00000000-0000-0000-0000-000000000001'::uuid
          AND status = 'success'
          AND finished_at IS NOT NULL
    ) THEN
        RAISE EXCEPTION 'FAIL: service_role could not update pipeline run';
    END IF;
END;
$update$;

DO $delete$
DECLARE
    blocked boolean := false;
BEGIN
    BEGIN
        DELETE FROM public.pipeline_runs
        WHERE run_id = '00000000-0000-0000-0000-000000000001'::uuid;
    EXCEPTION
        WHEN insufficient_privilege THEN
            blocked := true;
    END;
    IF NOT blocked THEN
        RAISE EXCEPTION 'FAIL: service_role can delete pipeline runs';
    END IF;
END;
$delete$;

RESET ROLE;

DO $constraints$
DECLARE
    blocked boolean;
BEGIN
    blocked := false;
    BEGIN
        INSERT INTO public.pipeline_runs (
            run_id, stage, mode, status, started_at
        )
        VALUES (
            '00000000-0000-0000-0000-000000000002',
            'ranking',
            'invalid_mode',
            'running',
            now()
        );
    EXCEPTION
        WHEN check_violation THEN
            blocked := true;
    END;
    IF NOT blocked THEN
        RAISE EXCEPTION 'FAIL: invalid mode was accepted';
    END IF;

    blocked := false;
    BEGIN
        INSERT INTO public.pipeline_runs (
            run_id, stage, mode, status, started_at
        )
        VALUES (
            '00000000-0000-0000-0000-000000000003',
            'ranking',
            'read_only',
            'invalid_status',
            now()
        );
    EXCEPTION
        WHEN check_violation THEN
            blocked := true;
    END;
    IF NOT blocked THEN
        RAISE EXCEPTION 'FAIL: invalid status was accepted';
    END IF;

    blocked := false;
    BEGIN
        INSERT INTO public.pipeline_runs (
            run_id, stage, mode, status, started_at, finished_at
        )
        VALUES (
            '00000000-0000-0000-0000-000000000004',
            'ranking',
            'read_only',
            'running',
            now(),
            now()
        );
    EXCEPTION
        WHEN check_violation THEN
            blocked := true;
    END;
    IF NOT blocked THEN
        RAISE EXCEPTION 'FAIL: running row with finished_at was accepted';
    END IF;

    blocked := false;
    BEGIN
        INSERT INTO public.pipeline_runs (
            run_id, stage, mode, status, started_at, finished_at
        )
        VALUES (
            '00000000-0000-0000-0000-000000000005',
            'ranking',
            'read_only',
            'success',
            now(),
            now() - interval '1 minute'
        );
    EXCEPTION
        WHEN check_violation THEN
            blocked := true;
    END;
    IF NOT blocked THEN
        RAISE EXCEPTION 'FAIL: finished_at before started_at was accepted';
    END IF;

    blocked := false;
    BEGIN
        INSERT INTO public.pipeline_runs (
            run_id, stage, mode, status, started_at, metrics
        )
        VALUES (
            '00000000-0000-0000-0000-000000000006',
            'ranking',
            'read_only',
            'running',
            now(),
            '[]'::jsonb
        );
    EXCEPTION
        WHEN check_violation THEN
            blocked := true;
    END;
    IF NOT blocked THEN
        RAISE EXCEPTION 'FAIL: non-object metrics were accepted';
    END IF;

    blocked := false;
    BEGIN
        INSERT INTO public.pipeline_runs (
            run_id, stage, mode, status, started_at, details
        )
        VALUES (
            '00000000-0000-0000-0000-000000000007',
            'ranking',
            'read_only',
            'running',
            now(),
            '[]'::jsonb
        );
    EXCEPTION
        WHEN check_violation THEN
            blocked := true;
    END;
    IF NOT blocked THEN
        RAISE EXCEPTION 'FAIL: non-object details were accepted';
    END IF;
END;
$constraints$;

ROLLBACK;
