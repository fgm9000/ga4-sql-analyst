"""Runtime configuration read from GA4_* environment variables (12-factor)."""

from pathlib import Path
from typing import Annotated

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

DEFAULT_GCP_PROJECT = "fgm9000-portfolio"
DEFAULT_VERTEX_LOCATION = "global"
DEFAULT_MODEL_ID = "gemini-3.1-flash-lite"
DEFAULT_MAX_BYTES_BILLED = 400_000_000
DEFAULT_RATE_PER_MINUTE = 5
DEFAULT_DAILY_REQUESTS = 200
DEFAULT_DAILY_LLM_CALLS = 80
DEFAULT_CACHE_MAX_ENTRIES = 500
DEFAULT_CORS_ORIGINS = ["https://fgm9000.github.io"]
DEFAULT_SAMPLE_PATH = Path("tests/fixtures/ga4_sample.parquet")
DEFAULT_WEB_DIR = Path("web")


class Settings(BaseSettings):
    """Application settings. Every field is overridable with a GA4_<FIELD> variable."""

    model_config = SettingsConfigDict(env_prefix="GA4_", env_file=None, frozen=True)

    gcp_project: str = DEFAULT_GCP_PROJECT
    vertex_location: str = DEFAULT_VERTEX_LOCATION
    model_id: str = DEFAULT_MODEL_ID
    max_bytes_billed: int = Field(default=DEFAULT_MAX_BYTES_BILLED, gt=0)
    rate_per_minute: int = Field(default=DEFAULT_RATE_PER_MINUTE, gt=0)
    daily_requests: int = Field(default=DEFAULT_DAILY_REQUESTS, gt=0)
    daily_llm_calls: int = Field(default=DEFAULT_DAILY_LLM_CALLS, gt=0)
    cache_max_entries: int = Field(default=DEFAULT_CACHE_MAX_ENTRIES, gt=0)
    cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: list(DEFAULT_CORS_ORIGINS)
    )
    offline: bool = False
    sample_path: Path = DEFAULT_SAMPLE_PATH
    web_dir: Path = DEFAULT_WEB_DIR

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_cors_origins(cls, value: object) -> object:
        """Accept a comma-separated string from the environment or a list from code."""
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value
