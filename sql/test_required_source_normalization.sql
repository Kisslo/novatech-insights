-- Local/CI only. Test records are rolled back.
-- Run after migration 007.
\set ON_ERROR_STOP on

BEGIN;

DO $test$
DECLARE
    saved_news_id bigint;
    rejected boolean;
BEGIN
    IF current_database() NOT IN (
        'novatech_test',
        'novatech_permissions_test'
    ) THEN
        RAISE EXCEPTION 'Run only in a local or CI test database';
    END IF;

    -- A correctly normalized article must still save.
    INSERT INTO public.news (
        title, link, source, source_normalized, published
    )
    VALUES (
        'Required source-key test',
        'https://example.com/required-source-key-valid',
        'Straße',
        'strasse',
        now()
    )
    RETURNING id INTO saved_news_id;

    -- Omitting the comparison key must fail.
    rejected := false;
    BEGIN
        INSERT INTO public.news (title, link, source, published)
        VALUES (
            'Missing source-key test',
            'https://example.com/required-source-key-missing',
            'Reuters',
            now()
        );
    EXCEPTION
        WHEN not_null_violation THEN
            rejected := true;
    END;

    IF NOT rejected THEN
        RAISE EXCEPTION 'FAIL: article without normalized key was accepted';
    END IF;

    -- An existing key must not be cleared to NULL.
    rejected := false;
    BEGIN
        UPDATE public.news
        SET source_normalized = NULL
        WHERE id = saved_news_id;
    EXCEPTION
        WHEN not_null_violation THEN
            rejected := true;
    END;

    IF NOT rejected THEN
        RAISE EXCEPTION 'FAIL: normalized key could be cleared to NULL';
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM public.news
        WHERE id = saved_news_id
          AND source = 'Straße'
          AND source_normalized = 'strasse'
    ) THEN
        RAISE EXCEPTION 'FAIL: valid source values were not preserved';
    END IF;

    RAISE NOTICE 'PASS: valid normalized article saves';
    RAISE NOTICE 'PASS: missing keys and NULL updates are rejected';
END;
$test$;

ROLLBACK;