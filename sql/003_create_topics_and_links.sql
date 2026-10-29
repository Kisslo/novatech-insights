-- Draft migration for issue #26.
-- Local testing only until reviewed.
-- Proposed names: topics and topic_articles.
-- Proposed llm_relevance type: whole numbers from 1 to 5.
-- Similarity storage and backend permissions remain pending.

BEGIN;

CREATE TABLE public.topics (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,

    label text,
    why_relevant_sv text,
    llm_relevance smallint,

    score double precision,
    score_calculated_at timestamptz,
    score_version text,
    score_breakdown jsonb,

    CONSTRAINT topics_label_not_blank
        CHECK (label IS NULL OR btrim(label) <> ''),

    CONSTRAINT topics_explanation_not_blank
        CHECK (
            why_relevant_sv IS NULL
            OR btrim(why_relevant_sv) <> ''
        ),

    CONSTRAINT topics_relevance_range
        CHECK (llm_relevance BETWEEN 1 AND 5),

    CONSTRAINT topics_score_finite
        CHECK (
            score > '-Infinity'::double precision
            AND score < 'Infinity'::double precision
        ),

    CONSTRAINT topics_score_version_not_blank
        CHECK (
            score_version IS NULL
            OR btrim(score_version) <> ''
        ),

    CONSTRAINT topics_breakdown_is_object
        CHECK (jsonb_typeof(score_breakdown) = 'object'),

    CONSTRAINT topics_score_fields_together
        CHECK (
            (
                score IS NULL
                AND score_calculated_at IS NULL
                AND score_version IS NULL
                AND score_breakdown IS NULL
            )
            OR
            (
                score IS NOT NULL
                AND score_calculated_at IS NOT NULL
                AND score_version IS NOT NULL
                AND score_breakdown IS NOT NULL
            )
        )
);

CREATE TABLE public.topic_articles (
    topic_id bigint NOT NULL,
    news_id bigint NOT NULL,

    PRIMARY KEY (topic_id, news_id),

    CONSTRAINT topic_articles_topic_fk
        FOREIGN KEY (topic_id)
        REFERENCES public.topics(id)
        ON DELETE RESTRICT,

    CONSTRAINT topic_articles_news_fk
        FOREIGN KEY (news_id)
        REFERENCES public.news(id)
        ON DELETE RESTRICT
);

CREATE INDEX topic_articles_news_id_idx
ON public.topic_articles (news_id);

ALTER TABLE public.topics ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.topic_articles ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON TABLE public.topics FROM PUBLIC;
REVOKE ALL ON TABLE public.topic_articles FROM PUBLIC;

COMMENT ON TABLE public.topics IS
'Topic ranking and generated labels. Draft schema for issue #26.';

COMMENT ON TABLE public.topic_articles IS
'Article-topic memberships. Each article-topic pair occurs once.';

COMMIT;