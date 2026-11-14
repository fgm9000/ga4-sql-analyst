"""Tests for the BigQuery and DuckDB warehouse adapters (no network)."""

from collections.abc import Callable, Iterable
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from google.api_core.exceptions import BadRequest
from google.auth.exceptions import DefaultCredentialsError
from google.cloud import bigquery

from ga4_sql_analyst.errors import WarehouseUnavailableError
from ga4_sql_analyst.warehouse import (
    OFFLINE_DEFAULT_BYTES,
    OFFLINE_FULL_SCAN_BYTES,
    BigQueryJob,
    BigQueryRow,
    BigQueryWarehouse,
    DuckDbWarehouse,
    create_bigquery_warehouse,
)

PARQUET = Path(__file__).parent / "fixtures" / "ga4_sample.parquet"
TABLE = "`bigquery-public-data.ga4_obfuscated_sample_ecommerce.events_*`"
MAX_BYTES = 1_000_000


def _q(template: str) -> str:
    """Expand the table placeholder (keeps SQL literals free of string interpolation)."""
    return template.replace("<T>", TABLE)


def _error(factory: Callable[[str], Exception], message: str) -> Exception:
    """Build a google exception through a typed callable (their constructors are untyped)."""
    return factory(message)


class _Opaque:
    def __str__(self) -> str:
        return "opaque-value"


class _FakeRow:
    def __init__(self, data: dict[str, object]) -> None:
        self._data = data

    def items(self) -> Iterable[tuple[str, object]]:
        return self._data.items()


class _FakeJob:
    def __init__(self, total_bytes: int | None, rows: list[dict[str, object]]) -> None:
        self._total_bytes = total_bytes
        self._rows = rows

    @property
    def total_bytes_processed(self) -> int | None:
        return self._total_bytes

    def result(self) -> Iterable[BigQueryRow]:
        return [_FakeRow(row) for row in self._rows]


class _FakeClient:
    def __init__(
        self,
        job: BigQueryJob | None = None,
        error: Exception | None = None,
    ) -> None:
        self._job = job
        self._error = error
        self.configs: list[bigquery.QueryJobConfig | None] = []

    def query(self, query: str, job_config: bigquery.QueryJobConfig | None = None) -> BigQueryJob:
        self.configs.append(job_config)
        if self._error is not None:
            raise self._error
        assert self._job is not None
        return self._job


class _FailingResultJob:
    @property
    def total_bytes_processed(self) -> int | None:
        return 0

    def result(self) -> Iterable[BigQueryRow]:
        raise _error(BadRequest, "boom")


def test_bigquery_dry_run_returns_bytes_and_uses_dry_run_config() -> None:
    client = _FakeClient(job=_FakeJob(1234, []))
    assert BigQueryWarehouse(client).dry_run("SELECT 1") == 1234
    config = client.configs[0]
    assert config is not None
    assert config.dry_run is True
    assert config.use_query_cache is False


def test_bigquery_dry_run_none_bytes_is_zero() -> None:
    client = _FakeClient(job=_FakeJob(None, []))
    assert BigQueryWarehouse(client).dry_run("SELECT 1") == 0


def test_bigquery_execute_converts_cells_and_sets_ceiling() -> None:
    raw: dict[str, object] = {
        "s": "text",
        "i": 3,
        "f": 1.5,
        "b": True,
        "n": None,
        "dec": Decimal("2.50"),
        "day": date(2021, 1, 31),
        "ts": datetime(2021, 1, 31, 12, 0, tzinfo=UTC),
        "other": _Opaque(),
    }
    client = _FakeClient(job=_FakeJob(0, [raw]))
    rows = BigQueryWarehouse(client).execute("SELECT 1", MAX_BYTES)
    assert rows == [
        {
            "s": "text",
            "i": 3,
            "f": 1.5,
            "b": True,
            "n": None,
            "dec": 2.5,
            "day": "2021-01-31",
            "ts": "2021-01-31T12:00:00+00:00",
            "other": "opaque-value",
        }
    ]
    assert isinstance(rows[0]["dec"], float)
    config = client.configs[0]
    assert config is not None
    assert config.maximum_bytes_billed == MAX_BYTES
    assert config.use_query_cache is True


@pytest.mark.parametrize(
    "error", [_error(BadRequest, "bad"), _error(DefaultCredentialsError, "no creds")]
)
def test_bigquery_query_errors_become_warehouse_unavailable(error: Exception) -> None:
    warehouse = BigQueryWarehouse(_FakeClient(error=error))
    with pytest.raises(WarehouseUnavailableError) as dry_info:
        warehouse.dry_run("SELECT 1")
    assert dry_info.value.__cause__ is error
    with pytest.raises(WarehouseUnavailableError) as exec_info:
        warehouse.execute("SELECT 1", MAX_BYTES)
    assert exec_info.value.__cause__ is error


def test_bigquery_result_error_becomes_warehouse_unavailable() -> None:
    warehouse = BigQueryWarehouse(_FakeClient(job=_FailingResultJob()))
    with pytest.raises(WarehouseUnavailableError):
        warehouse.execute("SELECT 1", MAX_BYTES)


def test_create_bigquery_warehouse_builds_client_with_project(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    projects: list[str] = []

    class _StubClient(_FakeClient):
        def __init__(self, project: str) -> None:
            super().__init__(job=_FakeJob(77, []))
            projects.append(project)

    monkeypatch.setattr(bigquery, "Client", _StubClient)
    warehouse = create_bigquery_warehouse("my-project")
    assert projects == ["my-project"]
    assert warehouse.dry_run("SELECT 1") == 77


def test_duckdb_execute_scenario_1_with_wildcard_and_suffix() -> None:
    sql = (
        "SELECT traffic_source.medium AS canal, "
        "SUM(ecommerce.purchase_revenue_in_usd) AS receita "
        "FROM <T> WHERE _TABLE_SUFFIX BETWEEN '20210102' AND '20210131' "
        "GROUP BY canal ORDER BY receita DESC LIMIT 100"
    )
    rows = DuckDbWarehouse(PARQUET).execute(_q(sql), MAX_BYTES)
    assert len(rows) >= 1
    assert set(rows[0]) == {"canal", "receita"}


def test_duckdb_execute_converts_values() -> None:
    sql = "SELECT CAST('2021-01-31' AS DATE) AS d, CAST(2.5 AS DECIMAL(4, 1)) AS n"
    rows = DuckDbWarehouse(PARQUET).execute(sql, MAX_BYTES)
    assert rows == [{"d": "2021-01-31", "n": 2.5}]


@pytest.mark.parametrize(
    "sql",
    [
        _q("SELECT * FROM <T>"),
        _q("SELECT e.* FROM <T> AS e"),
        _q("SELECT event_name FROM (SELECT * FROM <T>)"),
    ],
)
def test_duckdb_dry_run_star_is_full_scan(sql: str) -> None:
    assert DuckDbWarehouse(PARQUET).dry_run(sql) == OFFLINE_FULL_SCAN_BYTES


@pytest.mark.parametrize(
    "sql",
    [
        _q("SELECT event_name FROM <T>"),
        _q("SELECT COUNT(*) AS n FROM <T>"),
    ],
)
def test_duckdb_dry_run_named_columns_is_default(sql: str) -> None:
    assert DuckDbWarehouse(PARQUET).dry_run(sql) == OFFLINE_DEFAULT_BYTES


def test_duckdb_dry_run_invalid_sql_raises() -> None:
    with pytest.raises(WarehouseUnavailableError):
        DuckDbWarehouse(PARQUET).dry_run("SELEC FROM WHERE (")


@pytest.mark.parametrize(
    "sql",
    ["SELEC FROM WHERE (", _q("SELECT no_such_column FROM <T>")],
)
def test_duckdb_execute_invalid_sql_raises(sql: str) -> None:
    with pytest.raises(WarehouseUnavailableError):
        DuckDbWarehouse(PARQUET).execute(sql, MAX_BYTES)
