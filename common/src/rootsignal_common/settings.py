"""Settings shared by every Python component, loaded from environment variables and the repo-root ``.env``."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


def _find_env_file() -> Path | None:
    """Walk up from the working directory to find the repo's .env (so tools work from any sub-folder)."""
    for directory in [Path.cwd(), *Path.cwd().parents]:
        candidate = directory / ".env"
        if candidate.is_file():
            return candidate
    return None


class BaseServiceSettings(BaseSettings):
    """Base class: each component subclasses this and adds its own fields."""

    model_config = SettingsConfigDict(env_file=_find_env_file(), extra="ignore", env_file_encoding="utf-8")

    postgres_user: str = "rootsignal"
    postgres_password: str = "rootsignal-local-dev"
    postgres_db: str = "rootsignal"
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    database_url: str | None = None

    alert_service_url: str = "http://localhost:8080"
    internal_api_token: str = "change-me-local-only"

    embeddings_provider: str = "local"  # "local" (fastembed/ONNX) or "hash" (deterministic, tests/CI)
    embeddings_model: str = "sentence-transformers/all-MiniLM-L6-v2"

    @property
    def dsn(self) -> str:
        if self.database_url:
            return self.database_url
        return (
            f"postgresql://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )


@lru_cache
def common_settings() -> BaseServiceSettings:
    return BaseServiceSettings()
