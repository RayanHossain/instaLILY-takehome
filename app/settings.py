"""Application settings, read from the .env file (environment variables win)."""

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Typed settings. Copy .env.example to .env to get a working set of values."""

    # hide_input_in_errors: a bad or missing .env value raises an error that would
    # otherwise print the values it read, including the API key.
    model_config = SettingsConfigDict(env_file=".env", hide_input_in_errors=True)

    database_url: str
    coveo_org_id: str
    # SecretStr prints as '**********', so the key stays out of reprs and logs.
    coveo_api_key: SecretStr
