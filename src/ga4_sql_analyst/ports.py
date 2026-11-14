"""Abstractions the service depends on (Dependency Inversion). Adapters live in other modules."""

from collections.abc import Sequence
from typing import Protocol

from ga4_sql_analyst.models import CellValue, Lang, Period, SqlDraft

Row = dict[str, CellValue]


class SqlGenerator(Protocol):
    """Turns a question into a validated SQL draft.

    Raises SqlRejectedError when the SQL keeps failing deterministic checks after retries,
    and LlmUnavailableError when the provider fails.
    """

    async def generate(self, question: str, lang: Lang, period: Period | None) -> SqlDraft:
        """Return a SQL draft that already passed C01-C03."""


class Summarizer(Protocol):
    """Writes an executive summary grounded on the query result rows.

    Raises LlmUnavailableError when the provider fails.
    """

    async def summarize(self, question: str, lang: Lang, sql: str, rows: Sequence[Row]) -> str:
        """Return the summary text (numbers are grounded later by C06)."""


class Warehouse(Protocol):
    """Estimates and executes read-only SQL written in the BigQuery dialect.

    Raises WarehouseUnavailableError on any backend failure.
    """

    def dry_run(self, sql: str) -> int:
        """Return the estimated bytes the query would process."""

    def execute(self, sql: str, max_bytes_billed: int) -> list[Row]:
        """Run the query and return its rows as plain dicts."""
