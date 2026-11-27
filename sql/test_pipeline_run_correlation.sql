-- Local/CI test for the pipeline-run correlation extension.
\set ON_ERROR_STOP on

BEGIN;

DO $test$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'pipeline_runs'
          AND column_name = 'correlation_id'
          AND data_type = 'uuid'
    ) THEN
        RAISE EXCEPTION 'FAIL: pipeline_runs.correlation_id is missing';
    END IF;
END;
$test$;

INSERT INTO public.pipeline_runs (
    run_id,
    correlation_id,
    stage,
    mode,
    status,
    started_at,
    finished_at
)
VALUES (
    '10000000-0000-0000-0000-000000000001',
    '10000000-0000-0000-0000-000000000011',
    'ranking',
    'read_only',
    'success',
    now() - interval '1 minute',
    now()
);

INSERT INTO public.pipeline_runs (
    run_id,
    correlation_id,
    stage,
    mode,
    status,
    started_at,
    finished_at
)
VALUES (
    '10000000-0000-0000-0000-000000000002',
    '10000000-0000-0000-0000-000000000003',
    'grouping',
    'write',
    'success',
    now() - interval '1 minute',
    now()
);

DO $test$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM public.pipeline_runs
        WHERE run_id = '10000000-0000-0000-0000-000000000001'::uuid
          AND correlation_id = '10000000-0000-0000-0000-000000000011'::uuid
    ) THEN
        RAISE EXCEPTION 'FAIL: standalone run_id/correlation_id contract was not accepted';
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM public.pipeline_runs
        WHERE run_id = '10000000-0000-0000-0000-000000000002'::uuid
          AND correlation_id = '10000000-0000-0000-0000-000000000003'::uuid
    ) THEN
        RAISE EXCEPTION 'FAIL: shared correlation_id was not stored';
    END IF;
END;
$test$;

INSERT INTO public.pipeline_runs (
    run_id,
    correlation_id,
    stage,
    mode,
    status,
    started_at,
    finished_at
)
VALUES (
    '10000000-0000-0000-0000-000000000012',
    '10000000-0000-0000-0000-000000000012',
    'ranking',
    'read_only',
    'success',
    now() - interval '1 minute',
    now()
);

DO $test$
DECLARE
    supported_stage text;
BEGIN
    FOREACH supported_stage IN ARRAY ARRAY[
        'collection',
        'upload',
        'grouping',
        'ranking',
        'labeling',
        'draft_generation',
        'telegram'
    ] LOOP
        INSERT INTO public.pipeline_runs (
            run_id, correlation_id, stage, mode, status, started_at
        )
        VALUES (
            md5(supported_stage)::uuid,
            md5(supported_stage || '-correlation')::uuid,
            supported_stage,
            'read_only',
            'running',
            now()
        );
    END LOOP;
END;
$test$;

DO $test$
DECLARE
    blocked boolean := false;
BEGIN
    BEGIN
        INSERT INTO public.pipeline_runs (
            run_id, correlation_id, stage, mode, status, started_at
        )
        VALUES (
            '10000000-0000-0000-0000-000000000004',
            '10000000-0000-0000-0000-000000000004',
            'invalid_stage',
            'read_only',
            'running',
            now()
        );
    EXCEPTION
        WHEN check_violation THEN
            blocked := true;
    END;

    IF NOT blocked THEN
        RAISE EXCEPTION 'FAIL: unsupported stage was accepted';
    END IF;
END;
$test$;

ROLLBACK;
