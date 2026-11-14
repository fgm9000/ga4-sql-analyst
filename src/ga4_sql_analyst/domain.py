"""Pure domain rules: SQL guardrails, period resolution, cost ceiling, number grounding.

No I/O, no network, no clock access. Every function is deterministic.
"""

import re
import unicodedata
from collections.abc import Mapping, Sequence
from datetime import date, timedelta

import sqlglot
from sqlglot import exp

from ga4_sql_analyst.models import CellValue, CheckResult, Lang, Period
from ga4_sql_analyst.sql_rules import (
    ALLOWED_DATASET,
    ALLOWED_PROJECT,
    BIGQUERY_DIALECT,
    DAILY_TABLE_PATTERN,
    MAX_ROWS,
    WILDCARD_TABLE,
    SqlValidation,
    is_events_table,
    validate_sql,
)

__all__ = [
    "ALLOWED_DATASET",
    "ALLOWED_PROJECT",
    "DAILY_TABLE_PATTERN",
    "DATASET_END",
    "DATASET_START",
    "LOCAL_TABLE",
    "MAX_ROWS",
    "MIN_BILLED_BYTES",
    "WILDCARD_TABLE",
    "SqlValidation",
    "check_cost",
    "ground_summary_numbers",
    "period_bounds",
    "resolve_period",
    "rewrite_for_duckdb",
    "validate_sql",
]

DATASET_START = date(2020, 11, 1)
DATASET_END = date(2021, 1, 31)
LOCAL_TABLE = "events"
MIN_BILLED_BYTES = 10 * 1024**2
REL_TOLERANCE = 0.005

DUCKDB_DIALECT = "duckdb"
SUFFIX_COLUMN = "_TABLE_SUFFIX"
LOCAL_DATE_COLUMN = "event_date"
UNNEST_MAX_DEPTH = 2
UNGROUNDED_MARKER = "[?]"
PERCENT_SCALE = 100
MONTHS_PER_QUARTER = 3

_PERIOD_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("today", re.compile(r"\b(?:hoje|today)\b")),
    ("yesterday", re.compile(r"\b(?:ontem|yesterday)\b")),
    ("days", re.compile(r"\b(?:ultimos|ultimas|last)\s+(\d{1,4})\s+(?:dias|days)\b")),
    ("week", re.compile(r"\b(?:ultima semana|last week)\b")),
    ("this_month", re.compile(r"\b(?:este mes|this month)\b")),
    ("last_month", re.compile(r"\b(?:ultimo mes|mes passado|last month)\b")),
    ("last_quarter", re.compile(r"\b(?:ultimo trimestre|last quarter)\b")),
)

_DATE_FORMATS = (
    r"\d{1,2}/\d{1,2}/\d{4}|\d{4}-\d{1,2}-\d{1,2}|\d{1,2}\.\d{1,2}\.\d{4}"
    # Compact YYYYMMDD, as in _TABLE_SUFFIX bounds the LLM may echo.
    r"|20\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])(?!\d|[.,]\d)"
)
_NUMBER_PATTERN = re.compile(rf"(?<!\w)(?:(?P<date>{_DATE_FORMATS})|-?\d+(?:[.,]\d+)*(?P<pct>%)?)")
_SEPARATORS: dict[Lang, tuple[str, str]] = {"pt": (".", ","), "en": (",", ".")}
THOUSANDS_GROUP_DIGITS = 3


# --- Period resolution (C04) ----------------------------------------------------------------


def _normalize_text(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.lower())
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def _first_day_of_month(day: date) -> date:
    return day.replace(day=1)


def _quarter_start(day: date) -> date:
    month = ((day.month - 1) // MONTHS_PER_QUARTER) * MONTHS_PER_QUARTER + 1
    return day.replace(month=month, day=1)


def _previous_month_bounds(anchor: date) -> tuple[date, date]:
    end = _first_day_of_month(anchor) - timedelta(days=1)
    return _first_day_of_month(end), end


def _previous_quarter_bounds(anchor: date) -> tuple[date, date]:
    end = _quarter_start(anchor) - timedelta(days=1)
    return _quarter_start(end), end


def _days_back(days: int) -> tuple[date, date]:
    return DATASET_END - timedelta(days=days - 1), DATASET_END


def _bounds_for_rule(rule: str, match: re.Match[str]) -> tuple[date, date] | None:
    if rule == "today":
        return DATASET_END, DATASET_END
    if rule == "yesterday":
        day = DATASET_END - timedelta(days=1)
        return day, day
    if rule == "days":
        days = int(match.group(1))
        return _days_back(days) if days > 0 else None
    if rule == "week":
        return _days_back(7)
    if rule == "this_month":
        return _first_day_of_month(DATASET_END), DATASET_END
    if rule == "last_month":
        return _previous_month_bounds(DATASET_END)
    return _previous_quarter_bounds(DATASET_END)


def _earliest_match(text: str) -> tuple[str, re.Match[str]] | None:
    found: list[tuple[str, re.Match[str]]] = []
    for rule, pattern in _PERIOD_PATTERNS:
        match = pattern.search(text)
        if match is not None:
            found.append((rule, match))
    if not found:
        return None
    return min(found, key=lambda item: item[1].start())


def resolve_period(question: str) -> Period | None:
    """Resolve a relative period expression (PT/EN) anchored on DATASET_END (C04)."""
    earliest = _earliest_match(_normalize_text(question))
    if earliest is None:
        return None
    bounds = _bounds_for_rule(*earliest)
    if bounds is None:
        return None
    start, end = max(bounds[0], DATASET_START), bounds[1]
    if start > end:
        return None
    return Period(start=start, end=end, anchored=True)


def period_bounds(period: Period) -> tuple[str, str]:
    """Return (start, end) formatted as YYYYMMDD for _TABLE_SUFFIX filters."""
    return period.start.strftime("%Y%m%d"), period.end.strftime("%Y%m%d")


# --- DuckDB rewrite -------------------------------------------------------------------------


def _local_table_like(table: exp.Table) -> exp.Table:
    local = exp.to_table(LOCAL_TABLE)
    alias = table.args.get("alias")
    if alias is not None:
        local.set("alias", alias)
    return local


def _flatten_unnest(unnest: exp.Unnest) -> exp.Subquery:
    """DuckDB returns the whole STRUCT in one column; BigQuery exposes its fields."""
    depth = exp.PropertyEQ(
        this=exp.to_identifier("max_depth"),
        expression=exp.Literal.number(UNNEST_MAX_DEPTH),
    )
    call = exp.Anonymous(this="UNNEST", expressions=[unnest.expressions[0], depth])
    return exp.Subquery(this=exp.select(call))


def _rewrite_node(node: exp.Expression) -> exp.Expression:
    if isinstance(node, exp.Table) and is_events_table(node):
        return _local_table_like(node)
    if isinstance(node, exp.Column) and node.name.upper() == SUFFIX_COLUMN:
        return exp.column(LOCAL_DATE_COLUMN, table=node.table or None)
    if isinstance(node, exp.Unnest) and isinstance(node.parent, exp.From) and not node.alias:
        return _flatten_unnest(node)
    return node


def rewrite_for_duckdb(bigquery_sql: str) -> str:
    """Rewrite validated BigQuery SQL so it runs on the local DuckDB sample.

    Wildcard and daily source tables become LOCAL_TABLE (a daily table in the sample reads the
    whole period; only tests rely on this), _TABLE_SUFFIX becomes event_date and alias-less
    UNNEST in FROM is expanded one STRUCT level.
    """
    tree = sqlglot.parse_one(bigquery_sql, read=BIGQUERY_DIALECT)
    return tree.transform(_rewrite_node).sql(dialect=DUCKDB_DIALECT)


# --- Cost ceiling (C05) ---------------------------------------------------------------------


def check_cost(bytes_estimated: int, max_bytes: int) -> CheckResult:
    """C05: billed bytes (BigQuery minimum applies) must not exceed the ceiling."""
    if bytes_estimated < 0 or max_bytes <= 0:
        raise ValueError("bytes_estimated must be >= 0 and max_bytes must be > 0")
    billed = max(bytes_estimated, MIN_BILLED_BYTES)
    return CheckResult(
        id="C05_cost_ceiling",
        passed=billed <= max_bytes,
        detail=f"billed={billed} max={max_bytes}",
        bytes_estimated=bytes_estimated,
    )


# --- Summary grounding (C06) ----------------------------------------------------------------


def _decimal_separator(body: str, lang: Lang) -> str | None:
    """Pick the decimal separator of a token, accepting the other locale when unambiguous."""
    thousands, decimal = _SEPARATORS[lang]
    separators = [char for char in body if char in thousands + decimal]
    if not separators:
        return None
    if len(set(separators)) == 2:
        return separators[-1]
    if len(separators) > 1:
        return None
    is_group_of_three = len(body.split(separators[0])[1]) == THOUSANDS_GROUP_DIGITS
    return separators[0] if separators[0] == decimal or not is_group_of_three else None


def _parse_number(token: str, lang: Lang) -> tuple[float, int]:
    """Return (value, written decimal places) for a number token."""
    sign = -1.0 if token.startswith("-") else 1.0
    body = token.lstrip("-")
    decimal_separator = _decimal_separator(body, lang)
    integer_part, fraction = body, ""
    if decimal_separator is not None:
        integer_part, _, fraction = body.rpartition(decimal_separator)
    digits = "".join(char for char in integer_part if char.isdigit())
    return sign * float(f"{digits}.{fraction or '0'}"), len(fraction)


def _reference_values(
    rows: Sequence[Mapping[str, CellValue]], context_numbers: frozenset[float]
) -> list[float]:
    values = [float(value) for value in context_numbers]
    for row in rows:
        values.extend(
            float(cell)
            for cell in row.values()
            if isinstance(cell, int | float) and not isinstance(cell, bool)
        )
    return values


def _is_close(number: float, reference: float) -> bool:
    return abs(number - reference) <= REL_TOLERANCE * max(abs(reference), 1)


def _is_grounded(
    number: float, decimals: int, *, has_percent: bool, references: Sequence[float]
) -> bool:
    for reference in references:
        if _is_close(number, reference) or round(reference, decimals) == number:
            return True
        if has_percent and _is_close(number, reference * PERCENT_SCALE):
            return True
    return False


def ground_summary_numbers(
    summary: str,
    rows: Sequence[Mapping[str, CellValue]],
    lang: Lang,
    context_numbers: frozenset[float],
) -> tuple[str, CheckResult]:
    """C06: replace numbers not traceable to the rows or the context with [?]."""
    references = _reference_values(rows, context_numbers)
    ungrounded: list[str] = []

    def _replace(match: re.Match[str]) -> str:
        if match.group("date") is not None:
            return match.group(0)
        has_percent = match.group("pct") is not None
        token = match.group(0).removesuffix("%")
        value, decimals = _parse_number(token, lang)
        if _is_grounded(value, decimals, has_percent=has_percent, references=references):
            return match.group(0)
        ungrounded.append(token)
        return UNGROUNDED_MARKER + ("%" if has_percent else "")

    grounded_summary = _NUMBER_PATTERN.sub(_replace, summary)
    detail = f"ungrounded:{','.join(ungrounded)}" if ungrounded else None
    result = CheckResult(id="C06_summary_numbers", passed=not ungrounded, detail=detail)
    return grounded_summary, result
