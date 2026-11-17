-- Persistent execution history for backend pipeline stages.

BEGIN;

CREATE TABLE public.pipeline_runs (
    run_id uuid PRIMARY KEY,
    stage text NOT NULL,
    mode text NOT NULL,
    status text NOT NULL,
    started_at timestamptz NOT NULL,
    finished_at timestamptz,
    metrics jsonb NOT NULL DEFAULT '{}'::jsonb,
    details jsonb NOT NULL DEFAULT '{}'::jsonb,

    CONSTRAINT pipeline_runs_stage_allowed
        CHECK (stage IN ('ranking')),

    CONSTRAINT pipeline_runs_mode_allowed
        CHECK (mode IN ('read_only', 'write')),

    CONSTRAINT pipeline_runs_status_allowed
        CHECK (
            status IN ('running', 'success', 'partial', 'failed', 'no_data')
        ),

    CONSTRAINT pipeline_runs_metrics_object
        CHECK (jsonb_typeof(metrics) = 'object'),

    CONSTRAINT pipeline_runs_details_object
        CHECK (jsonb_typeof(details) = 'object'),

    CONSTRAINT pipeline_runs_finished_after_started
        CHECK (finished_at IS NULL OR finished_at >= started_at),

    CONSTRAINT pipeline_runs_running_without_finish
        CHECK (
            (status = 'running' AND finished_at IS NULL)
            OR
            (status <> 'running' AND finished_at IS NOT NULL)
        )
);

CREATE INDEX pipeline_runs_stage_started_at_idx
ON public.pipeline_runs (stage, started_at DESC);

ALTER TABLE public.pipeline_runs ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON TABLE public.pipeline_runs FROM PUBLIC;

DO $permissions$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_roles WHERE rolname = 'anon'
    ) THEN
        REVOKE ALL ON TABLE public.pipeline_runs FROM anon;
    END IF;
    IF EXISTS (
        SELECT 1 FROM pg_roles WHERE rolname = 'authenticated'
    ) THEN
        REVOKE ALL ON TABLE public.pipeline_runs FROM authenticated;
    END IF;
    IF EXISTS (
        SELECT 1 FROM pg_roles WHERE rolname = 'service_role'
    ) THEN
        GRANT USAGE ON SCHEMA public TO service_role;
        GRANT SELECT, INSERT, UPDATE
        ON TABLE public.pipeline_runs TO service_role;
    ELSE
        RAISE NOTICE
            'service_role does not exist; pipeline run grants were skipped';
    END IF;
END;
$permissions$;

COMMENT ON TABLE public.pipeline_runs IS
'Persistent execution history for backend pipeline stages.';

COMMENT ON COLUMN public.pipeline_runs.metrics IS
'Run counters. Ranking uses topics, error, write and warning counts.';

COMMENT ON COLUMN public.pipeline_runs.details IS
'Run-level and per-topic errors, skips and warning text.';

COMMIT;
