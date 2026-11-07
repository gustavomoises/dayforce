CREATE TABLE IF NOT EXISTS query_embeddings (
    query_hash char(64) PRIMARY KEY,
    model text NOT NULL,
    embedding vector(1536) NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
