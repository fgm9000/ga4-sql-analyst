"""Warehouse adapters: BigQuery (production) and DuckDB over the local Parquet sample (offline)."""

from collections.abc import Iterable
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Protocol

import duckdb
import sqlglot
from google.api_core.exceptions import GoogleAPIError
from google.auth.exceptions import GoogleAuthError
from google.cloud import bigquery
from sqlglot import exp
from sqlglot.errors import SqlglotError

from ga4_sql_analyst.domain import LOCAL_TABLE, rewrite_for_duckdb
from ga4_sql_analyst.errors import WarehouseUnavailableError
from ga4_sql_analyst.models import CellValue
from ga4_sql_analyst.ports import Row
from ga4_sql_analyst.sql_rules import BIGQUERY_DIALECT

OFFLINE_FULL_SCAN_BYTES = 3_583_657_854  # measured on the full table in spike 2
OFFLINE_DEFAULT_BYTES = 0


class BigQueryRow(Protocol):
    """The slice of a BigQuery result row that the adapter reads."""

    def items(self) -> Iterable[tuple[str, object]]:
        """Return (column, value) pairs."""


class BigQueryJob(Protocol):
    """The slice of a BigQuery query job that the adapter reads."""

    @property
    def total_bytes_processed(self) -> int | None:
        """Bytes processed (estimated for dry runs); None when unknown."""

    def result(self) -> Iterable[BigQueryRow]:
        """Wait for the job and iterate its rows."""


class BigQueryClient(Protocol):
    """The slice of `bigquery.Client` that the adapter calls."""

    def query(self, query: str, job_config: bigquery.QueryJobConfig | None = None) -> BigQueryJob:
        """Start a query job."""


def _to_cell(value: object) -> CellValue:
    """Convert a warehouse value into a JSON-friendly cell."""
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, date):  # datetime is a date subclass
        return value.isoformat()
    return str(value)


def _to_row(pairs: Iterable[tuple[str, object]]) -> Row:
    return {name: _to_cell(value) for name, value in pairs}


class BigQueryWarehouse:
    """Runs read-only SQL on BigQuery with a dry run estimate and a billed-bytes ceiling."""

    def __init__(self, client: BigQueryClient) -> None:
        self._client = client

    def dry_run(self, sql: str) -> int:
        """Return the estimated bytes processed, without running the query."""
        config = bigquery.QueryJobConfig(dry_run=True, use_query_cache=False)
        try:
            job = self._client.query(sql, job_config=config)
        except (GoogleAPIError, GoogleAuthError) as exc:
            raise WarehouseUnavailableError(str(exc)) from exc
        return job.total_bytes_processed or 0

    def execute(self, sql: str, max_bytes_billed: int) -> list[Row]:
        """Run the query with `maximum_bytes_billed` set and return plain rows."""
        config = bigquery.QueryJobConfig(
            maximum_bytes_billed=max_bytes_billed, use_query_cache=True
        )
        try:
            job = self._client.query(sql, job_config=config)
            return [_to_row(row.items()) for row in job.result()]
        except (GoogleAPIError, GoogleAuthError) as exc:
            raise WarehouseUnavailableError(str(exc)) from exc


def create_bigquery_warehouse(project: str) -> BigQueryWarehouse:
    """Build a BigQueryWarehouse on a real client (uses application default credentials)."""
    return BigQueryWarehouse(bigquery.Client(project=project))


def _has_star_projection(select: exp.Select) -> bool:
    for projection in select.expressions:
        if isinstance(projection, exp.Star):
            return True
        if isinstance(projection, exp.Column) and isinstance(projection.this, exp.Star):
            return True
    return False


class DuckDbWarehouse:
    """Runs BigQuery-dialect SQL on the local Parquet sample through DuckDB (offline mode)."""

    def __init__(self, parquet_path: Path) -> None:
        self._con = duckdb.connect()
        self._con.read_parquet(str(parquet_path)).create_view(LOCAL_TABLE)

    def dry_run(self, sql: str) -> int:
        """Return a deterministic offline byte estimate; nothing is executed.

        A SELECT (including subqueries and CTEs) that projects `*` or `alias.*` counts as a
        full scan and returns OFFLINE_FULL_SCAN_BYTES; every other query returns
        OFFLINE_DEFAULT_BYTES.
        """
        try:
            tree = sqlglot.parse_one(sql, read=BIGQUERY_DIALECT)
        except SqlglotError as exc:
            raise WarehouseUnavailableError(str(exc)) from exc
        if any(_has_star_projection(select) for select in tree.find_all(exp.Select)):
            return OFFLINE_FULL_SCAN_BYTES
        return OFFLINE_DEFAULT_BYTES

    def execute(self, sql: str, max_bytes_billed: int) -> list[Row]:
        """Rewrite the SQL for DuckDB and run it. `max_bytes_billed` is ignored offline."""
        try:
            cursor = self._con.execute(rewrite_for_duckdb(sql))
            names = [column[0] for column in cursor.description]
            return [_to_row(zip(names, values, strict=True)) for values in cursor.fetchall()]
        except (duckdb.Error, SqlglotError) as exc:
            raise WarehouseUnavailableError(str(exc)) from exc
