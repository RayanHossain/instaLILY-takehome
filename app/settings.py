"""Application settings: values from the .env file (environment variables win), and the
territory and selling points from config/distributor.yaml."""

from pathlib import Path
from typing import Any

import yaml
from pydantic import PositiveInt, SecretStr
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
    # Optional, so the UI and the other stages run without one: only discover needs it, and says so.
    coveo_api_key: SecretStr | None = None
    # Optional, so the UI runs without one: only the AI stages need it, and app/ai says so.
    gemini_api_key: SecretStr | None = None
    # The model every AI call uses, and the most requests to send it per minute. 31B gave
    # valid answers for 10 of 10 sample contractors; 26B A4B looped on 4 of them.
    gemini_model: str = "gemma-4-31b-it"
    gemini_requests_per_minute: PositiveInt = 10
    # How many leads each scoring preset contributes to the brief stage: its top N by total.
    top_leads_per_preset: PositiveInt = 10


def load_territory() -> dict[str, Any]:
    """Read the territory (zip, lat, lng, radius_miles) from config/distributor.yaml."""
    return yaml.safe_load(Path("config/distributor.yaml").read_text())["territory"]


def load_selling_points() -> dict[str, str]:
    """Read the selling points from config/distributor.yaml: id -> its one-line description."""
    points = yaml.safe_load(Path("config/distributor.yaml").read_text())["selling_points"]
    return {point["id"]: point["description"] for point in points}
