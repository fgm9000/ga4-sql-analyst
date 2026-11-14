"""Tests for AskService with typed doubles and the real DuckDB warehouse (no network)."""

from collections.abc import Sequence
from pathlib import Path

import pytest

from ga4_sql_analyst.errors import (
    LlmUnavailableError,
    SqlRejectedError,
    WarehouseUnavailableError,
)
from ga4_sql_analyst.models import AskRequest, AskResponse, Lang, Period, SqlDraft
from ga4_sql_analyst.ports import Row
from ga4_sql_analyst.scenarios import SCENARIOS, Scenario
from ga4_sql_analyst.service import AskService
from ga4_sql_analyst.snapshot import Snapshot, SnapshotEntry
from ga4_sql_analyst.warehouse import DuckDbWarehouse

PARQUET = Path(__file__).parent / "fixtures" / "ga4_sample.parquet"
MAX_BYTES = 1024**3
CACHED = "cached summary"
DELETE_SQL = (
    "DELETE FROM `bigquery-public-data.ga4_obfuscated_sample_ecommerce.events_*` WHERE true"
)


class _Generator:
    def __init__(self, outcome: SqlDraft | Exception) -> None:
        self._outcome = outcome

    async def generate(self, question: str, lang: Lang, period: Period | None) -> SqlDraft:
        if isinstance(self._outcome, Exception):
            raise self._outcome
        return self._outcome


class _Summarizer:
    def __init__(self, outcome: str | Exception) -> None:
        self._outcome = outcome

    async def summarize(self, question: str, lang: Lang, sql: str, rows: Sequence[Row]) -> str:
        if isinstance(self._outcome, Exception):
            raise self._outcome
        return self._outcome


class _Warehouse:
    """Warehouse double with fixed bytes and rows; optional failure per method."""

    def __init__(
        self, bytes_estimated: int = 0, dry_run_error: bool = False, execute_error: bool = False
    ) -> None:
        self._bytes = bytes_estimated
        self._dry_run_error = dry_run_error
        self._execute_error = execute_error

    def dry_run(self, sql: str) -> int:
        if self._dry_run_error:
            raise WarehouseUnavailableError("dry run down")
        return self._bytes

    def execute(self, sql: str, max_bytes_billed: int) -> list[Row]:
        if self._execute_error:
            raise WarehouseUnavailableError("execute down")
        return [{"channel": "referral", "revenue": 215.0}]


def _draft(sql: str) -> SqlDraft:
    return SqlDraft(sql=sql, tables=["events_*"], intent="test")


def _snapshot_for(scenario: Scenario) -> Snapshot:
    response = AskResponse(status="answered", summary=CACHED)
    entries = [
        SnapshotEntry(scenario=scenario.scenario, lang="pt", question=question, response=response)
        for question in (scenario.question["pt"],)
    ]
    return Snapshot(entries)


def _service(
    generator: _Generator,
    summarizer: _Summarizer | None = None,
    warehouse: _Warehouse | DuckDbWarehouse | None = None,
    snapshot: Snapshot | None = None,
) -> AskService:
    return AskService(
        generator,
        summarizer or _Summarizer("Top channel: referral."),
        warehouse or _Warehouse(),
        snapshot or Snapshot([]),
        MAX_BYTES,
    )


def _request(scenario: Scenario, lang: Lang = "pt") -> AskRequest:
    return AskRequest(question=scenario.question[lang], lang=lang)


def _real_service(scenario: Scenario, summary: str) -> AskService:
    return _service(
        _Generator(_draft(scenario.offline_sql)),
        _Summarizer(summary),
        DuckDbWarehouse(PARQUET),
    )


@pytest.mark.anyio
@pytest.mark.parametrize("lang", ["pt", "en"])
async def test_scenario_one_is_answered_with_grounded_summary(lang: Lang) -> None:
    scenario = SCENARIOS[0]
    service = _real_service(scenario, "In 30 days (2021-01-02), referral made 215 in revenue.")
    response = await service.ask(_request(scenario, lang))
    assert response.status == "answered"
    assert response.degraded is False
    assert response.period is not None
    assert response.rows
    ids = [check.id for check in response.checks]
    assert ids == [
        "C04_date_anchor",
        "C01_select_only",
        "C02_allowed_tables",
        "C03_limit",
        "C05_cost_ceiling",
        "C06_summary_numbers",
    ]
    assert all(check.passed for check in response.checks)
    assert response.summary is not None
    assert "[?]" not in response.summary


@pytest.mark.anyio
async def test_scenario_two_is_answered_without_period() -> None:
    scenario = SCENARIOS[1]
    response = await _real_service(scenario, "Desktop has the most views.").ask(_request(scenario))
    assert response.status == "answered"
    assert response.period is None
    assert response.checks[0].detail == "no_relative_period"
    assert {row["device_category"] for row in response.rows} >= {"desktop", "mobile"}


@pytest.mark.anyio
async def test_scenario_three_is_blocked_by_cost() -> None:
    scenario = SCENARIOS[2]
    response = await _real_service(scenario, "unused").ask(_request(scenario))
    assert response.status == "blocked"
    assert response.reason == "cost_ceiling"
    assert response.sql is not None
    assert response.rows == []
    assert response.checks[-1].id == "C05_cost_ceiling"
    assert response.checks[-1].passed is False


@pytest.mark.anyio
async def test_scenario_four_is_blocked_when_generator_rejects() -> None:
    scenario = SCENARIOS[3]
    service = _service(_Generator(SqlRejectedError("not_select")))
    response = await service.ask(_request(scenario))
    assert response.status == "blocked"
    assert response.reason == "not_select"
    assert response.sql is None
    assert [(check.id, check.passed) for check in response.checks] == [
        ("C04_date_anchor", True),
        ("C01_select_only", False),
    ]


@pytest.mark.anyio
async def test_revalidation_blocks_sql_that_slipped_past_the_generator() -> None:
    scenario = SCENARIOS[3]
    response = await _service(_Generator(_draft(DELETE_SQL))).ask(_request(scenario))
    assert response.status == "blocked"
    assert response.reason == "not_select"
    assert [check.passed for check in response.checks] == [True, False, False, False]


@pytest.mark.anyio
async def test_llm_unavailable_without_snapshot_hit() -> None:
    service = _service(_Generator(LlmUnavailableError()))
    response = await service.ask(_request(SCENARIOS[0]))
    assert response.status == "unavailable"
    assert response.reason == "llm_unavailable"
    assert response.period is not None


@pytest.mark.anyio
async def test_llm_unavailable_serves_degraded_snapshot() -> None:
    scenario = SCENARIOS[0]
    service = _service(_Generator(LlmUnavailableError()), snapshot=_snapshot_for(scenario))
    response = await service.ask(_request(scenario))
    assert response.status == "answered"
    assert response.degraded is True
    assert response.summary == CACHED


@pytest.mark.anyio
async def test_dry_run_failure_without_snapshot_hit() -> None:
    scenario = SCENARIOS[0]
    service = _service(
        _Generator(_draft(scenario.offline_sql)), warehouse=_Warehouse(dry_run_error=True)
    )
    response = await service.ask(_request(scenario))
    assert response.status == "answered"
    assert response.degraded is True
    assert response.reason == "warehouse_unavailable"
    assert response.sql is not None
    assert response.rows == []
    assert response.summary is None
    assert response.checks[-1].id == "C03_limit"


@pytest.mark.anyio
async def test_execute_failure_serves_degraded_snapshot() -> None:
    scenario = SCENARIOS[0]
    service = _service(
        _Generator(_draft(scenario.offline_sql)),
        warehouse=_Warehouse(execute_error=True),
        snapshot=_snapshot_for(scenario),
    )
    response = await service.ask(_request(scenario))
    assert response.degraded is True
    assert response.summary == CACHED
    assert response.reason is None


@pytest.mark.anyio
async def test_snapshot_miss_for_other_language_keeps_warehouse_reason() -> None:
    scenario = SCENARIOS[0]
    service = _service(
        _Generator(_draft(scenario.offline_sql)),
        warehouse=_Warehouse(dry_run_error=True),
        snapshot=_snapshot_for(scenario),
    )
    response = await service.ask(_request(scenario, "en"))
    assert response.reason == "warehouse_unavailable"
    assert response.summary is None


@pytest.mark.anyio
async def test_summary_failure_returns_rows_without_summary() -> None:
    scenario = SCENARIOS[0]
    service = _service(
        _Generator(_draft(scenario.offline_sql)),
        _Summarizer(LlmUnavailableError()),
    )
    response = await service.ask(_request(scenario))
    assert response.status == "answered"
    assert response.degraded is True
    assert response.reason == "summary_unavailable"
    assert response.summary is None
    assert response.rows == [{"channel": "referral", "revenue": 215.0}]


@pytest.mark.anyio
async def test_invented_number_is_marked_by_c06() -> None:
    scenario = SCENARIOS[0]
    service = _service(
        _Generator(_draft(scenario.offline_sql)),
        _Summarizer("Referral made 999 in revenue."),
    )
    response = await service.ask(_request(scenario))
    assert response.status == "answered"
    assert response.summary == "Referral made [?] in revenue."
    c06 = response.checks[-1]
    assert c06.id == "C06_summary_numbers"
    assert c06.passed is False
    assert c06.detail == "ungrounded:999"
