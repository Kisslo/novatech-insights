-- Post-backfill migration for issue #26.
-- Run only after source normalization has been backfilled and verified.
-- All article writers must supply source_normalized before applying this.
-- An empty string remains valid for a missing or blank source name.

BEGIN;

-- PostgreSQL rejects this change if any existing row contains NULL.
-- Once applied, inserts and updates cannot store a NULL comparison key.
ALTER TABLE public.news
ALTER COLUMN source_normalized SET NOT NULL;

COMMIT;