-- Source registry for source-type-based ranking.
-- Ranking parameters belong in the ranking configuration.
-- Existing article and feed tables are preserved.

BEGIN;

CREATE TABLE public.source_registry (
    source_normalized text COLLATE "C" PRIMARY KEY,
    name text NOT NULL,
    source_type text,

    CONSTRAINT source_registry_key_not_blank
        CHECK (source_normalized ~ '[^[:space:]]'),

    CONSTRAINT source_registry_name_not_blank
        CHECK (name ~ '[^[:space:]]'),

    CONSTRAINT source_registry_type_allowed
        CHECK (source_type IN ('media', 'authority'))
);

ALTER TABLE public.source_registry ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON TABLE public.source_registry FROM PUBLIC;

-- Backend access is read-only; administrators maintain the registry.
DO $permissions$
DECLARE
    role_name text;
BEGIN
    FOR role_name IN
        SELECT rolname
        FROM pg_roles
        WHERE rolname IN ('anon', 'authenticated', 'service_role')
    LOOP
        EXECUTE format(
            'REVOKE ALL ON TABLE public.source_registry FROM %I',
            role_name
        );
    END LOOP;

    IF EXISTS (
        SELECT 1 FROM pg_roles WHERE rolname = 'service_role'
    ) THEN
        GRANT USAGE ON SCHEMA public TO service_role;
        GRANT SELECT ON TABLE public.source_registry TO service_role;
    ELSE
        RAISE NOTICE
            'service_role does not exist; registry SELECT grant was skipped';
    END IF;
END;
$permissions$;

COMMENT ON TABLE public.source_registry IS
'Source metadata for source-type-based ranking.
Ranking parameters are defined in configuration, not per source here.
Classification criteria and process require team agreement.';

COMMENT ON COLUMN public.source_registry.source_normalized IS
'Comparison key generated using the shared Python normalize_source helper.
Matches news.source_normalized. SQL does not reproduce Python casefold.
No foreign key is imposed on existing article sources.';

COMMENT ON COLUMN public.source_registry.name IS
'Source display name. Does not replace existing news.source values.';

COMMENT ON COLUMN public.source_registry.source_type IS
'media or authority. NULL means not yet classified.
Do not infer classifications before the criteria are agreed.';

COMMIT;