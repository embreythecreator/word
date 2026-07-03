CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS open_notebook (
    id text PRIMARY KEY,
    credentials jsonb NOT NULL DEFAULT '{}'::jsonb,
    default_chat_model text,
    default_transformation_model text,
    large_context_model text,
    default_text_to_speech_model text,
    default_speech_to_text_model text,
    default_embedding_model text,
    default_tools_model text,
    created timestamptz NOT NULL DEFAULT now(),
    updated timestamptz NOT NULL DEFAULT now()
);

INSERT INTO open_notebook (id, default_chat_model)
VALUES ('open_notebook:default_models', '')
ON CONFLICT (id) DO NOTHING;

INSERT INTO open_notebook (id, credentials)
VALUES ('open_notebook:provider_configs', '{}'::jsonb)
ON CONFLICT (id) DO NOTHING;

CREATE TABLE IF NOT EXISTS notebook (
    id text PRIMARY KEY,
    name text,
    description text,
    archived boolean NOT NULL DEFAULT false,
    created timestamptz NOT NULL DEFAULT now(),
    updated timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS source (
    id text PRIMARY KEY,
    asset jsonb,
    title text,
    topics jsonb NOT NULL DEFAULT '[]'::jsonb,
    full_text text,
    command text,
    created timestamptz NOT NULL DEFAULT now(),
    updated timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS source_embedding (
    id text PRIMARY KEY,
    source text REFERENCES source(id) ON DELETE CASCADE,
    "order" integer,
    content text NOT NULL,
    embedding vector({{EMBEDDING_DIMENSION}}),
    created timestamptz NOT NULL DEFAULT now(),
    updated timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS source_insight (
    id text PRIMARY KEY,
    source text REFERENCES source(id) ON DELETE CASCADE,
    insight_type text NOT NULL,
    content text NOT NULL,
    embedding vector({{EMBEDDING_DIMENSION}}),
    created timestamptz NOT NULL DEFAULT now(),
    updated timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS note (
    id text PRIMARY KEY,
    title text,
    summary text,
    note_type text,
    content text,
    embedding vector({{EMBEDDING_DIMENSION}}),
    created timestamptz NOT NULL DEFAULT now(),
    updated timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS reference (
    id text PRIMARY KEY,
    in_id text NOT NULL REFERENCES source(id) ON DELETE CASCADE,
    out_id text NOT NULL REFERENCES notebook(id) ON DELETE CASCADE,
    created timestamptz NOT NULL DEFAULT now(),
    updated timestamptz NOT NULL DEFAULT now(),
    UNIQUE (in_id, out_id)
);

CREATE TABLE IF NOT EXISTS artifact (
    id text PRIMARY KEY,
    in_id text NOT NULL REFERENCES note(id) ON DELETE CASCADE,
    out_id text NOT NULL REFERENCES notebook(id) ON DELETE CASCADE,
    created timestamptz NOT NULL DEFAULT now(),
    updated timestamptz NOT NULL DEFAULT now(),
    UNIQUE (in_id, out_id)
);

CREATE TABLE IF NOT EXISTS chat_session (
    id text PRIMARY KEY,
    title text,
    model_override text,
    created timestamptz NOT NULL DEFAULT now(),
    updated timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS refers_to (
    id text PRIMARY KEY,
    in_id text NOT NULL REFERENCES chat_session(id) ON DELETE CASCADE,
    out_id text NOT NULL,
    created timestamptz NOT NULL DEFAULT now(),
    updated timestamptz NOT NULL DEFAULT now(),
    UNIQUE (in_id, out_id)
);

CREATE TABLE IF NOT EXISTS transformation (
    id text PRIMARY KEY,
    name text NOT NULL,
    title text NOT NULL,
    description text NOT NULL,
    prompt text NOT NULL,
    apply_default boolean NOT NULL DEFAULT false,
    created timestamptz NOT NULL DEFAULT now(),
    updated timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS model (
    id text PRIMARY KEY,
    name text NOT NULL,
    provider text NOT NULL,
    type text NOT NULL,
    credential text,
    created timestamptz NOT NULL DEFAULT now(),
    updated timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS credential (
    id text PRIMARY KEY,
    name text NOT NULL,
    provider text NOT NULL,
    modalities jsonb NOT NULL DEFAULT '[]'::jsonb,
    api_key text,
    base_url text,
    endpoint text,
    api_version text,
    endpoint_llm text,
    endpoint_embedding text,
    endpoint_stt text,
    endpoint_tts text,
    project text,
    location text,
    credentials_path text,
    config jsonb,
    created timestamptz NOT NULL DEFAULT now(),
    updated timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS episode_profile (
    id text PRIMARY KEY,
    name text NOT NULL UNIQUE,
    description text,
    speaker_config text NOT NULL,
    outline_provider text,
    outline_model text,
    transcript_provider text,
    transcript_model text,
    outline_llm text,
    transcript_llm text,
    language text,
    default_briefing text NOT NULL,
    num_segments integer NOT NULL DEFAULT 5,
    created timestamptz NOT NULL DEFAULT now(),
    updated timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS speaker_profile (
    id text PRIMARY KEY,
    name text NOT NULL UNIQUE,
    description text,
    tts_provider text,
    tts_model text,
    voice_model text,
    speakers jsonb NOT NULL DEFAULT '[]'::jsonb,
    created timestamptz NOT NULL DEFAULT now(),
    updated timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS episode (
    id text PRIMARY KEY,
    name text NOT NULL,
    episode_profile jsonb NOT NULL,
    speaker_profile jsonb NOT NULL,
    briefing text NOT NULL,
    content text NOT NULL,
    audio_file text,
    transcript jsonb,
    outline jsonb,
    command text,
    created timestamptz NOT NULL DEFAULT now(),
    updated timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS command (
    id text PRIMARY KEY,
    app_id text NOT NULL,
    name text NOT NULL,
    status text NOT NULL DEFAULT 'pending',
    input jsonb NOT NULL DEFAULT '{}'::jsonb,
    result jsonb,
    error_message text,
    progress jsonb,
    created timestamptz NOT NULL DEFAULT now(),
    updated timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_source_embedding_source ON source_embedding(source);
CREATE INDEX IF NOT EXISTS idx_source_insight_source ON source_insight(source);
CREATE INDEX IF NOT EXISTS idx_reference_in_out ON reference(in_id, out_id);
CREATE INDEX IF NOT EXISTS idx_artifact_in_out ON artifact(in_id, out_id);
CREATE INDEX IF NOT EXISTS idx_refers_to_in_out ON refers_to(in_id, out_id);
CREATE INDEX IF NOT EXISTS idx_model_type ON model(type);
CREATE INDEX IF NOT EXISTS idx_model_credential ON model(credential);
CREATE INDEX IF NOT EXISTS idx_credential_provider ON credential(provider);
CREATE INDEX IF NOT EXISTS idx_command_status ON command(status);

CREATE INDEX IF NOT EXISTS idx_source_embedding_hnsw
ON source_embedding USING hnsw (embedding vector_cosine_ops)
WHERE embedding IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_source_insight_hnsw
ON source_insight USING hnsw (embedding vector_cosine_ops)
WHERE embedding IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_note_hnsw
ON note USING hnsw (embedding vector_cosine_ops)
WHERE embedding IS NOT NULL;
