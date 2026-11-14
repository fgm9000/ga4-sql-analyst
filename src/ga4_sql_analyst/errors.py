"""Domain exception hierarchy. Every predictable failure has its own type."""


class Ga4SqlAnalystError(Exception):
    """Base class for all project errors."""


class LlmUnavailableError(Ga4SqlAnalystError):
    """The LLM provider failed (timeout, HTTP error, quota) and produced no usable output."""


class SqlRejectedError(Ga4SqlAnalystError):
    """The LLM kept producing SQL that failed the deterministic checks after all retries."""

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


class WarehouseUnavailableError(Ga4SqlAnalystError):
    """The warehouse (BigQuery or DuckDB) could not estimate or execute a query."""
