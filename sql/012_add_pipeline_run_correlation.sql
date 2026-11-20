-- Add correlation tracing to public.pipeline_runs.
-- Stage and mode lists remain explicit shared contracts documented in code.

BEGIN;

ALTER TABLE public.pipeline_runs
ADD COLUMN correlation_id uuid;

ALTER TABLE public.pipeline_runs
DROP CONSTRAINT pipeline_runs_stage_allowed;

ALTER TABLE public.pipeline_runs
ADD CONSTRAINT pipeline_runs_stage_allowed
CHECK (
    stage IN (
        'collection',
        'upload',
        'grouping',
        'ranking',
        'labeling',
        'draft_generation',
        'telegram'
    )
);

CREATE INDEX pipeline_runs_correlation_started_at_idx
ON public.pipeline_runs (correlation_id, started_at DESC);

COMMENT ON COLUMN public.pipeline_runs.correlation_id IS
'Optional identifier for a related chain of pipeline stage runs.
run_id identifies one execution and remains separate.
A standalone run creates run_id and correlation_id with separate UUID calls.
An incoming correlation_id is reused; run_id is always created anew.
The values are allowed to be equal.';

COMMIT;
