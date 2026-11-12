-- Authority classifications for issue #52.
-- EU Digital Strategy and IMY were confirmed by Mathias.
-- CERT-SE and EDPB are proposed additions for review in PR #61.
-- Run after migration 009 and seed_source_registry.sql.
-- Other sources and ranking parameters are unchanged.
-- This DO statement is atomic and can run inside a test transaction.

DO $classification$
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
    ) <> cardinality(authority_keys) THEN
        RAISE EXCEPTION
            'Required authority sources are missing. Run the registry seed first.';
    END IF;

    UPDATE public.source_registry
    SET source_type = 'authority'
    WHERE source_normalized = ANY(authority_keys)
      AND source_type IS DISTINCT FROM 'authority';
END;
$classification$;