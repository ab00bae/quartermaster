"""Application settings, loaded from the environment."""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration.

    Every value can be overridden by an environment variable of the same name,
    so the container image is built once and configured per environment.
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "quartermaster"
    # SQLite by default so the project runs with no external services. Point this
    # at PostgreSQL (postgresql+psycopg://user:pass@host/db) for a real deployment.
    database_url: str = "sqlite:///./quartermaster.db"
    sql_echo: bool = False


@lru_cache
def get_settings() -> Settings:
    return Settings()
