"""Secret values loaded at startup. Values never appear in repr, logs or errors."""

from pydantic import BaseModel, ConfigDict, SecretStr


class DatabaseCredentials(BaseModel):
    model_config = ConfigDict(frozen=True)

    host: str
    port: int
    dbname: str
    username: str
    password: SecretStr


class Secrets(BaseModel):
    model_config = ConfigDict(frozen=True)

    database: DatabaseCredentials
    openai_api_key: SecretStr
    langfuse_public_key: SecretStr
    langfuse_secret_key: SecretStr
