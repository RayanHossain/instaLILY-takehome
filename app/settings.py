"""Application settings, read from environment variables and the .env file."""

from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Typed settings. Environment variables win over values in .env."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "sqlite:///data/leads.db"
    coveo_org_id: str = "gafmaterialscorporationproduction3yalqk12"
    # SecretStr prints as '**********', so the key never shows up in reprs or logs.
    coveo_api_key: SecretStr = SecretStr("")


@lru_cache
def get_settings() -> Settings:
    """Return the settings, loaded once per process."""
    return Settings()
