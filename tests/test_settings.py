"""Testes de settings.py."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from ga4_sql_analyst.settings import Settings


@pytest.fixture(autouse=True)
def _clean_ga4_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove every GA4_* variable so tests do not depend on the host environment."""
    for field_name in Settings.model_fields:
        monkeypatch.delenv(f"GA4_{field_name.upper()}", raising=False)


def test_defaults() -> None:
    settings = Settings()
    assert settings.gcp_project == "fgm9000-portfolio"
    assert settings.vertex_location == "global"
    assert settings.model_id == "gemini-3.1-flash-lite"
    assert settings.max_bytes_billed == 400_000_000
    assert settings.rate_per_minute == 5
    assert settings.daily_requests == 200
    assert settings.daily_llm_calls == 80
    assert settings.cache_max_entries == 500
    assert settings.cors_origins == ["https://fgm9000.github.io"]
    assert settings.offline is False
    assert settings.sample_path == Path("tests/fixtures/ga4_sample.parquet")


def test_reads_integer_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GA4_DAILY_LLM_CALLS", "10")
    assert Settings().daily_llm_calls == 10


def test_reads_bool_and_path_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GA4_OFFLINE", "1")
    monkeypatch.setenv("GA4_SAMPLE_PATH", "/data/sample.parquet")
    settings = Settings()
    assert settings.offline is True
    assert settings.sample_path == Path("/data/sample.parquet")


def test_cors_origins_from_comma_separated_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GA4_CORS_ORIGINS", "https://a.com, https://b.com")
    assert Settings().cors_origins == ["https://a.com", "https://b.com"]


def test_cors_origins_drops_empty_entries(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GA4_CORS_ORIGINS", " https://a.com ,, ")
    assert Settings().cors_origins == ["https://a.com"]


def test_cors_origins_accepts_list_in_code() -> None:
    assert Settings(cors_origins=["https://x.com"]).cors_origins == ["https://x.com"]


@pytest.mark.parametrize(
    "field_name",
    [
        "max_bytes_billed",
        "rate_per_minute",
        "daily_requests",
        "daily_llm_calls",
        "cache_max_entries",
    ],
)
@pytest.mark.parametrize("bad_value", ["0", "-1"])
def test_positive_limits_reject_zero_and_negative(
    monkeypatch: pytest.MonkeyPatch, field_name: str, bad_value: str
) -> None:
    monkeypatch.setenv(f"GA4_{field_name.upper()}", bad_value)
    with pytest.raises(ValidationError):
        Settings()


def test_settings_are_frozen() -> None:
    settings = Settings()
    with pytest.raises(ValidationError):
        settings.offline = True
