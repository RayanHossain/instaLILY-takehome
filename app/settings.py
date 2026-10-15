"""Application settings: values from the .env file (environment variables win), and the
territory from config/distributor.yaml."""

from pathlib import Path
from typing import Any

import yaml
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Typed settings. Copy .env.example to .env to get a working set of values."""

    # hide_input_in_errors: a bad or missing .env value raises an error that would
    # otherwise print the values it read, including the API key.
    # extra="ignore": .env may also hold keys for later slices that these settings don't read.
    model_config = SettingsConfigDict(env_file=".env", hide_input_in_errors=True, extra="ignore")

    database_url: str
    coveo_org_id: str
    # SecretStr prints as '**********', so the keys stay out of reprs and logs.
    coveo_api_key: SecretStr
    # Optional, so the UI runs without one: only the AI stages need it, and app/ai says so.
    gemini_api_key: SecretStr | None = None


def load_territory() -> dict[str, Any]:
    """Read the territory (zip, lat, lng, radius_miles) from config/distributor.yaml."""
    return yaml.safe_load(Path("config/distributor.yaml").read_text())["territory"]
