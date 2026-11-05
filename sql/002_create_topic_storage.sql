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
ALTER TABLE public.news
ADD COLUMN source_normalized text COLLATE "C";

COMMENT ON COLUMN public.news.source_normalized IS
'Source comparison key computed in Python using strip().casefold().
The original source column is preserved for display.
NULL means normalization has not been completed for this row.
An empty string represents a missing or blank source name.';

COMMIT;
