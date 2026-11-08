"""Non-secret settings, read from environment variables with defaults."""

import os

from pydantic import BaseModel, ConfigDict


class Settings(BaseModel):
    """Every field can be overridden by an env var of the same name in upper case."""

    model_config = ConfigDict(frozen=True)

    aws_region: str = "us-east-2"
    langfuse_host: str = "https://us.cloud.langfuse.com"

    embedding_model: str = "text-embedding-3-small"
    embedding_dimensions: int = 1536
    embedding_batch_size: int = 100
    embedding_timeout_seconds: float = 10.0
    llm_timeout_seconds: float = 30.0
    db_statement_timeout_ms: int = 5000

    vector_min_similarity: float = 0.30
    search_default_limit: int = 10
    search_max_limit: int = 50
    search_branch_limit: int = 50
    rrf_k: int = 60
    ivfflat_rows_per_list: int = 1000
    ivfflat_max_lists: int = 10
    ivfflat_probes: int = 10

    assist_max_results: int = 5
    assist_default_multiplier: int = 3
    assist_max_multiplier: int = 5
    validation_batch_size: int = 15
    validation_max_batches: int = 4
    max_question_length: int = 2000

    ingest_max_items: int = 500
    seed: int = 42
    seed_repeats: int = 1
    seed_min_incidents: int = 200
    seed_max_incidents: int = 999
    catalog_path: str = "data/service_catalog.json"

    @classmethod
    def from_env(cls) -> "Settings":
        """Build settings from env vars; unset vars keep their defaults."""
        values = {
            name: os.environ[name.upper()]
            for name in cls.model_fields
            if name.upper() in os.environ
        }
        return cls(**values)
