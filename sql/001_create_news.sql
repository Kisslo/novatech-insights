-- Initial setup for a database where public.news does not yet exist.
-- Already applied to the current Supabase project.
-- Does not modify public.news_articles.

CREATE TABLE public.news (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    title text NOT NULL CHECK (btrim(title) <> ''),
    link text NOT NULL UNIQUE CHECK (btrim(link) <> ''),
    source text NOT NULL,
    published timestamptz NOT NULL,
    subject text NOT NULL DEFAULT '',
    description text NOT NULL DEFAULT '',
    collected_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX news_published_idx
ON public.news (published DESC);

ALTER TABLE public.news ENABLE ROW LEVEL SECURITY;