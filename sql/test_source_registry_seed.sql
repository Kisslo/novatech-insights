-- LOCAL/CI ONLY.
-- Run with psql because this test uses \ir.
-- All test changes are rolled back.

BEGIN;

-- Temporary classifications to verify that the seed preserves them.
INSERT INTO public.source_registry (
    source_normalized, name, source_type
)
VALUES
    ('ai business', 'AI Business', 'media'),
    ('ars technica', 'Ars Technica', 'authority')
ON CONFLICT (source_normalized)
DO UPDATE SET source_type = EXCLUDED.source_type;

-- Remember every existing entry before seeding.
CREATE TEMP TABLE registry_before_seed ON COMMIT DROP AS
SELECT source_normalized, name, source_type
FROM public.source_registry;

-- Resolve the seed path relative to this test file.
\ir seed_source_registry.sql

CREATE TEMP TABLE registry_after_first_seed ON COMMIT DROP AS
SELECT source_normalized, name, source_type
FROM public.source_registry;

\ir seed_source_registry.sql

DO $tests$
DECLARE
    expected_sources text[] := ARRAY[
        'ai business',
        'ars technica',
        'bleepingcomputer',
        'breakit',
        'computer weekly',
        'dark reading',
        'engadget',
        'forskning.se',
        'geekwire',
        'github blog',
        'help net security',
        'infoq',
        'krebs on security',
        'mit technology review',
        'n8n blog',
        'schneier on security',
        'sciencedaily ai',
        'sd times',
        'securityweek',
        'siliconangle',
        'sweclockers',
        'tech xplore',
        'tech.eu',
        'techcrunch',
        'techrepublic',
        'the hacker news',
        'the new stack',
        'the register',
        'unite.ai',
        'wired'
    ];
BEGIN
    -- All 30 expected comparison keys must exist.
    IF EXISTS (
        SELECT 1
        FROM unnest(expected_sources) AS expected(source_key)
        WHERE NOT EXISTS (
            SELECT 1
            FROM public.source_registry AS actual
            WHERE actual.source_normalized = expected.source_key
        )
    ) THEN
        RAISE EXCEPTION 'FAIL: expected sources are missing';
    END IF;

    -- No source key may occur more than once.
    IF EXISTS (
        SELECT source_normalized
        FROM public.source_registry
        GROUP BY source_normalized
        HAVING COUNT(*) > 1
    ) THEN
        RAISE EXCEPTION 'FAIL: duplicate source keys exist';
    END IF;

    -- Existing names and classifications must survive both seed runs.
    IF EXISTS (
        SELECT source_normalized, name, source_type
        FROM registry_before_seed
        EXCEPT
        SELECT source_normalized, name, source_type
        FROM public.source_registry
    ) THEN
        RAISE EXCEPTION
            'FAIL: existing source data or classifications changed';
    END IF;

    -- Newly inserted sources must remain unclassified.
    IF EXISTS (
        SELECT 1
        FROM public.source_registry AS actual
        WHERE actual.source_type IS NOT NULL
          AND NOT EXISTS (
              SELECT 1
              FROM registry_before_seed AS original
              WHERE original.source_normalized = actual.source_normalized
          )
    ) THEN
        RAISE EXCEPTION 'FAIL: seed classified a new source';
    END IF;

    -- The second seed must not add or change anything.
    IF EXISTS (
        SELECT source_normalized, name, source_type
        FROM public.source_registry
        EXCEPT
        SELECT source_normalized, name, source_type
        FROM registry_after_first_seed
    ) OR EXISTS (
        SELECT source_normalized, name, source_type
        FROM registry_after_first_seed
        EXCEPT
        SELECT source_normalized, name, source_type
        FROM public.source_registry
    ) THEN
        RAISE EXCEPTION 'FAIL: repeated seed changed the registry';
    END IF;

    RAISE NOTICE
        'PASS: expected sources exist, no duplicates, classifications preserved';
END;
$tests$;

ROLLBACK;