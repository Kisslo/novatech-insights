-- Local/CI test only. Makes no database changes.
-- Run after migrations 001–005, BEFORE migration 006.
\set ON_ERROR_STOP on

DO $test$
DECLARE
    role_name text;
    object_name text;
    permission_name text;
BEGIN
    IF current_database() <> 'novatech_permissions_test' THEN
        RAISE EXCEPTION
            'Run only in the novatech_permissions_test database';
    END IF;

    FOREACH role_name IN ARRAY
        ARRAY['anon', 'authenticated', 'service_role']
    LOOP
        IF NOT EXISTS (
            SELECT 1 FROM pg_roles WHERE rolname = role_name
        ) THEN
            RAISE EXCEPTION
                'FAIL: required test role % is missing', role_name;
        END IF;

        IF has_function_privilege(
            role_name,
            'public.save_topic_group(bigint[])',
            'EXECUTE'
        ) THEN
            RAISE EXCEPTION
                'FAIL: role % can execute saving function before backend grants',
                role_name;
        END IF;

        FOREACH object_name IN ARRAY ARRAY[
            'public.topics',
            'public.topic_articles',
            'public.topic_overview',
            'public.topic_top_articles'
        ]
        LOOP
            IF to_regclass(object_name) IS NULL THEN
                RAISE EXCEPTION
                    'FAIL: expected object % is missing', object_name;
            END IF;

            FOREACH permission_name IN ARRAY ARRAY[
                'SELECT', 'INSERT', 'UPDATE', 'DELETE',
                'TRUNCATE', 'REFERENCES', 'TRIGGER', 'MAINTAIN'
            ]
            LOOP
                IF has_table_privilege(
                    role_name, object_name, permission_name
                ) THEN
                    RAISE EXCEPTION
                        'FAIL: role % still has % on %',
                        role_name, permission_name, object_name;
                END IF;
            END LOOP;
        END LOOP;

        IF to_regclass('public.topics_id_seq') IS NULL THEN
            RAISE EXCEPTION 'FAIL: topic ID sequence is missing';
        END IF;

        FOREACH permission_name IN ARRAY
            ARRAY['USAGE', 'SELECT', 'UPDATE']
        LOOP
            IF has_sequence_privilege(
                role_name, 'public.topics_id_seq', permission_name
            ) THEN
                RAISE EXCEPTION
                    'FAIL: role % still has % on topic ID sequence',
                    role_name, permission_name;
            END IF;
        END LOOP;

        -- Confirms the setup supplied broad grants and that
        -- the new migrations did not revoke existing news grants.
        FOREACH permission_name IN ARRAY ARRAY[
            'SELECT', 'INSERT', 'UPDATE', 'DELETE',
            'TRUNCATE', 'REFERENCES', 'TRIGGER', 'MAINTAIN'
        ]
        LOOP
            IF NOT has_table_privilege(
                role_name, 'public.news', permission_name
            ) THEN
                RAISE EXCEPTION
                    'FAIL: expected original news grant % missing for %',
                    permission_name, role_name;
            END IF;
        END LOOP;
    END LOOP;

    RAISE NOTICE
        'PASS: automatic grants removed from new tables, views and sequence';
    RAISE NOTICE
        'PASS: saving function execution denied before backend grants';
    RAISE NOTICE
        'PASS: existing news grants remain unchanged';
END;
$test$;