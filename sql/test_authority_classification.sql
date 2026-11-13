-- LOCAL/CI ONLY.
-- Run with psql because this test uses \ir.
-- All test changes are rolled back.

BEGIN;

\ir seed_source_registry.sql

-- Simulate existing unclassified sources.
UPDATE public.source_registry
SET source_type = NULL
WHERE source_normalized IN (
    'european commission digital strategy',
    'cert-se'
);

-- Simulate existing sources with a different classification.
UPDATE public.source_registry
SET source_type = 'media'
WHERE source_normalized IN (
    'imy',
    'european data protection board'
);

CREATE TEMP TABLE registry_before_classification ON COMMIT DROP AS
SELECT source_normalized, name, source_type
FROM public.source_registry;

\ir classify_authority_sources.sql

DO $tests$
DECLARE
    authority_keys text[] := ARRAY[
        'european commission digital strategy',
        'imy',
        'cert-se',
        'european data protection board'
    ];
BEGIN
    IF (
        SELECT COUNT(*)
        FROM public.source_registry
        WHERE source_normalized = ANY(authority_keys)
          AND source_type = 'authority'
    ) <> cardinality(authority_keys) THEN
        RAISE EXCEPTION
            'FAIL: expected sources were not classified as authority';
    END IF;

    -- Names and comparison keys must remain unchanged.
    IF EXISTS (
        SELECT source_normalized, name
        FROM registry_before_classification
        EXCEPT
        SELECT source_normalized, name
        FROM public.source_registry
    ) THEN
        RAISE EXCEPTION 'FAIL: source names or keys changed';
    END IF;

    -- Every other source must remain unchanged.
    IF EXISTS (
        SELECT source_normalized, name, source_type
        FROM registry_before_classification
        WHERE NOT (source_normalized = ANY(authority_keys))
        EXCEPT
        SELECT source_normalized, name, source_type
        FROM public.source_registry
    ) THEN
        RAISE EXCEPTION
            'FAIL: unrelated source classifications changed';
    END IF;

    -- Classification must not add or remove registry rows.
    IF (
        SELECT COUNT(*) FROM public.source_registry
    ) <> (
        SELECT COUNT(*) FROM registry_before_classification
    ) THEN
        RAISE EXCEPTION 'FAIL: registry row count changed';
    END IF;
END;
$tests$;

CREATE TEMP TABLE registry_after_classification ON COMMIT DROP AS
SELECT source_normalized, name, source_type
FROM public.source_registry;

-- Run again to verify repeatability.
\ir classify_authority_sources.sql

DO $tests$
BEGIN
    IF EXISTS (
        SELECT source_normalized, name, source_type
        FROM public.source_registry
        EXCEPT
        SELECT source_normalized, name, source_type
        FROM registry_after_classification
    ) OR EXISTS (
        SELECT source_normalized, name, source_type
        FROM registry_after_classification
        EXCEPT
        SELECT source_normalized, name, source_type
        FROM public.source_registry
    ) THEN
        RAISE EXCEPTION
            'FAIL: repeated classification changed the registry';
    END IF;

    RAISE NOTICE
        'PASS: four authority sources classified, other sources preserved, rerun safe';
END;
$tests$;

ROLLBACK;