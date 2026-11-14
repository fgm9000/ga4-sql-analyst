"""Tests for the offline model and service (DuckDB sample, no network)."""

from pathlib import Path

import pytest
from pydantic_ai.models.function import FunctionModel

from ga4_sql_analyst.models import AskRequest, Lang
from ga4_sql_analyst.offline import (
    DEFAULT_OFFLINE_SQL,
    EMPTY_TEXT,
    _scenario_sql,
    _summary_text,
    build_offline_model,
    build_offline_service,
)
from ga4_sql_analyst.scenarios import SCENARIOS

PARQUET = Path(__file__).parent / "fixtures" / "ga4_sample.parquet"
MAX_BYTES = 400_000_000
UNKNOWN_QUESTION = "How many sessions happened on mobile?"


def test_build_offline_model_returns_function_model() -> None:
    assert isinstance(build_offline_model(), FunctionModel)


def test_scenario_sql_matches_scenario_question() -> None:
    scenario = SCENARIOS[0]
    assert _scenario_sql(f"<question>{scenario.question['pt']}</question>") == scenario.offline_sql


def test_scenario_sql_falls_back_to_demo_query() -> None:
    assert _scenario_sql(UNKNOWN_QUESTION) == DEFAULT_OFFLINE_SQL


def test_summary_text_without_rows_uses_empty_text() -> None:
    assert _summary_text("<query_result>[]</query_result>", "pt") == EMPTY_TEXT["pt"]
    assert _summary_text("no result block", "en") == EMPTY_TEXT["en"]


@pytest.mark.anyio
@pytest.mark.parametrize("lang", ["pt", "en"])
async def test_service_answers_first_scenario(lang: Lang) -> None:
    service = build_offline_service(PARQUET, MAX_BYTES)
    response = await service.ask(AskRequest(question=SCENARIOS[0].question[lang], lang=lang))
    assert response.status == "answered"
    assert response.rows
    assert response.summary is not None
    assert not response.degraded


@pytest.mark.anyio
async def test_service_blocks_destructive_scenario() -> None:
    service = build_offline_service(PARQUET, MAX_BYTES)
    response = await service.ask(AskRequest(question=SCENARIOS[3].question["en"], lang="en"))
    assert response.status == "blocked"


@pytest.mark.anyio
async def test_service_blocks_full_scan_scenario_by_cost() -> None:
    service = build_offline_service(PARQUET, MAX_BYTES)
    response = await service.ask(AskRequest(question=SCENARIOS[2].question["pt"], lang="pt"))
    assert response.status == "blocked"
    assert response.reason == "cost_ceiling"


@pytest.mark.anyio
async def test_service_answers_unknown_question_with_demo_query() -> None:
    service = build_offline_service(PARQUET, MAX_BYTES)
    response = await service.ask(AskRequest(question=UNKNOWN_QUESTION, lang="en"))
    assert response.status == "answered"
    assert response.sql is not None
    assert "event_name" in response.sql
    assert 0 < len(response.rows) <= 10
