"""Application settings, read from the .env file (environment variables win)."""

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Typed settings. Copy .env.example to .env to get a working set of values."""

    model_config = SettingsConfigDict(env_file=".env")

    database_url: str
    coveo_org_id: str
    # SecretStr prints as '**********', so the key stays out of reprs and logs.
    coveo_api_key: SecretStr
