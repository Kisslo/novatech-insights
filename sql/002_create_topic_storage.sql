-- Draft migration for issue #26.
-- Local testing only until reviewed.
-- Topic tables and embedding tracking rules are still to be added.

BEGIN;

CREATE SCHEMA IF NOT EXISTS extensions;

CREATE EXTENSION IF NOT EXISTS vector
WITH SCHEMA extensions;

ALTER TABLE public.news
ADD COLUMN embedding extensions.vector(384);

COMMENT ON COLUMN public.news.embedding IS
'384-dimensional embedding from paraphrase-multilingual-MiniLM-L12-v2,
using title and RSS description. NULL means no embedding is stored.';

COMMIT;