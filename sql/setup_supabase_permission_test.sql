-- Local/CI test setup only. Never run in Supabase.
\set ON_ERROR_STOP on

BEGIN;

DO $setup$
BEGIN
    IF current_database() <> 'novatech_permissions_test' THEN
        RAISE EXCEPTION
            'Run only in the novatech_permissions_test database';
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
        CREATE ROLE anon NOLOGIN NOSUPERUSER NOBYPASSRLS;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_roles WHERE rolname = 'authenticated'
    ) THEN
        CREATE ROLE authenticated NOLOGIN NOSUPERUSER NOBYPASSRLS;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_roles WHERE rolname = 'service_role'
    ) THEN
        CREATE ROLE service_role NOLOGIN NOSUPERUSER BYPASSRLS;
    END IF;
END;
$setup$;

GRANT USAGE ON SCHEMA public
TO anon, authenticated, service_role;

ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public
GRANT ALL ON TABLES TO anon, authenticated, service_role;

ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public
GRANT ALL ON SEQUENCES TO anon, authenticated, service_role;

COMMIT;