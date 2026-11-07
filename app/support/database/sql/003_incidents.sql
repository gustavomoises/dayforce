CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS incidents (
    id text PRIMARY KEY CHECK (id ~ '^inc-[0-9]{5}$'),
    created_at timestamptz NOT NULL,
    environment_id smallint NOT NULL REFERENCES environment_types (id),
    service_id smallint NOT NULL REFERENCES service_types (id),
    severity_id smallint NOT NULL REFERENCES severity_types (id),
    title text NOT NULL,
    description text NOT NULL,
    resolution_summary text NOT NULL,
    content_hash char(64) NOT NULL,
    search_vector tsvector GENERATED ALWAYS AS (
        setweight(to_tsvector('english', title), 'A')
        || setweight(to_tsvector('english', description), 'B')
        || setweight(to_tsvector('english', resolution_summary), 'C')
    ) STORED,
    embedding vector(1536),
    embedding_model text,
    embedding_text_hash char(64),
    updated_at timestamptz NOT NULL DEFAULT now(),
    -- Deferred so one ingest batch may move a hash between rows in any order.
    CONSTRAINT incidents_content_hash_key UNIQUE (content_hash) DEFERRABLE INITIALLY DEFERRED
);

CREATE TABLE IF NOT EXISTS incident_tags (
    incident_id text NOT NULL REFERENCES incidents (id) ON DELETE CASCADE,
    tag_id integer NOT NULL REFERENCES tags (id) ON DELETE CASCADE,
    PRIMARY KEY (incident_id, tag_id)
);
