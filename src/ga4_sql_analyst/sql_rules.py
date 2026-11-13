"""SQL guardrails C01 (read-only), C02 (table allowlist) and C03 (row limit).

Pure functions over the sqlglot AST: no I/O, no clock access.
"""

import re
from dataclasses import dataclass

import sqlglot
from sqlglot import exp
from sqlglot.errors import SqlglotError

from ga4_sql_analyst.models import CheckId, CheckResult

ALLOWED_PROJECT = "bigquery-public-data"
ALLOWED_DATASET = "ga4_obfuscated_sample_ecommerce"
WILDCARD_TABLE = "events_*"
DAILY_TABLE_PATTERN = re.compile(r"events_\d{8}")
MAX_ROWS = 100
BIGQUERY_DIALECT = "bigquery"
NOT_EVALUATED = "not_evaluated"
SQL_CHECK_IDS: tuple[CheckId, ...] = ("C01_select_only", "C02_allowed_tables", "C03_limit")
SYSTEM_VARIABLE_PREFIX = "@@"
FORBIDDEN_FUNCTIONS = frozenset(
    {
        "SESSION_USER",
        "CURRENT_USER",
        "EXTERNAL_QUERY",
        "EXTERNAL_OBJECT_TRANSFORM",
        "VECTOR_SEARCH",
        "DETERMINISTIC_ENCRYPT",
        "DETERMINISTIC_DECRYPT",
    }
)
FORBIDDEN_FUNCTION_PREFIXES = frozenset({"ML", "AI", "KEYS", "AEAD"})
FORBIDDEN_FUNCTION_TYPES: dict[type[exp.Expression], str] = {
    exp.SessionUser: "SESSION_USER",
    exp.CurrentUser: "CURRENT_USER",
    exp.VectorSearch: "VECTOR_SEARCH",
    exp.Predict: "ML.PREDICT",
}

ROOT_TYPES: tuple[type[exp.Expression], ...] = (
    exp.Select,
    exp.Union,
    exp.Intersect,
    exp.Except,
)
FORBIDDEN_TYPES: tuple[type[exp.Expression], ...] = (
    exp.Insert,
    exp.Update,
    exp.Delete,
    exp.Merge,
    exp.Drop,
    exp.Create,
    exp.Alter,
    exp.Command,
    exp.TruncateTable,
)


@dataclass(frozen=True)
class SqlValidation:
    """Outcome of the SQL guardrails (C01, C02, C03)."""

    is_valid: bool
    sql: str
    checks: tuple[CheckResult, ...]
    reason: str | None


# --- SQL guardrails (C01, C02, C03) ---------------------------------------------------------


def is_events_table(table: exp.Table) -> bool:
    """True for the allowed project/dataset with the wildcard or a daily events table."""
    name = table.name.lower()
    is_events_name = name == WILDCARD_TABLE or DAILY_TABLE_PATTERN.fullmatch(name) is not None
    return (
        table.catalog.lower() == ALLOWED_PROJECT
        and table.db.lower() == ALLOWED_DATASET
        and is_events_name
    )


def _parse_select_only(sql: str) -> tuple[exp.Expression | None, str | None]:
    """Parse the SQL and return (tree, None) or (None, C01 failure code)."""
    try:
        statements = sqlglot.parse(sql, read=BIGQUERY_DIALECT)
    except (SqlglotError, RecursionError):
        return None, "parse_error"
    parsed = [statement for statement in statements if statement is not None]
    if not parsed:
        return None, "parse_error"
    if len(parsed) > 1:
        return None, "multiple_statements"
    root = parsed[0]
    if not isinstance(root, ROOT_TYPES):
        return None, "not_select"
    if root.find(*FORBIDDEN_TYPES) is not None:
        return None, "forbidden_statement"
    forbidden = _find_forbidden_function(root)
    if forbidden is not None:
        return None, f"forbidden_function:{forbidden}"
    return root, None


def _forbidden_function_name(node: exp.Expr) -> str | None:
    """Return the denylisted function or system variable a node represents, if any."""
    for node_type, name in FORBIDDEN_FUNCTION_TYPES.items():
        if isinstance(node, node_type):
            return name
    if isinstance(node, exp.Anonymous) and str(node.name).upper() in FORBIDDEN_FUNCTIONS:
        return str(node.name).upper()
    if isinstance(node, exp.Dot) and node.this.name.upper() in FORBIDDEN_FUNCTION_PREFIXES:
        function = node.expression
        return f"{node.this.name.upper()}.{(function.name or function.sql_name()).upper()}"
    if isinstance(node, exp.Parameter | exp.SessionParameter):
        text = node.sql(dialect=BIGQUERY_DIALECT)
        return text if text.startswith(SYSTEM_VARIABLE_PREFIX) else None
    return None


def _find_forbidden_function(root: exp.Expression) -> str | None:
    for node in root.walk():
        name = _forbidden_function_name(node)
        if name is not None:
            return name
    return None


def _table_full_name(table: exp.Table) -> str:
    parts = [part for part in (table.catalog, table.db, table.name) if part]
    return ".".join(parts)


def _table_violation(root: exp.Expression) -> str | None:
    """Return the C02 failure code: a disallowed table, or no allowed table at all."""
    cte_names = {cte.alias.lower() for cte in root.find_all(exp.CTE)}
    has_allowed_table = False
    for table in root.find_all(exp.Table):
        is_cte_reference = not table.catalog and not table.db and table.name.lower() in cte_names
        if is_cte_reference:
            continue
        if not is_events_table(table):
            return f"table_not_allowed:{_table_full_name(table)}"
        has_allowed_table = True
    return None if has_allowed_table else "no_allowed_table"


def _is_limit_within_cap(limit: exp.Expression) -> bool:
    value = limit.args.get("expression")
    return isinstance(value, exp.Literal) and value.is_int and int(value.name) <= MAX_ROWS


def _apply_limit(root: exp.Expression) -> tuple[str, CheckResult]:
    limit = root.args.get("limit")
    detail: str | None = None
    if limit is None:
        detail = "limit_injected"
    elif not _is_limit_within_cap(limit):
        detail = "limit_capped"
    if detail is not None:
        root.set("limit", exp.Limit(expression=exp.Literal.number(MAX_ROWS)))
    result = CheckResult(id="C03_limit", passed=True, detail=detail)
    return root.sql(dialect=BIGQUERY_DIALECT), result


def _blocked(sql: str, evaluated: tuple[CheckResult, ...], reason: str) -> SqlValidation:
    pending = tuple(
        CheckResult(id=check_id, passed=False, detail=NOT_EVALUATED)
        for check_id in SQL_CHECK_IDS[len(evaluated) :]
    )
    return SqlValidation(is_valid=False, sql=sql, checks=evaluated + pending, reason=reason)


def validate_sql(sql: str) -> SqlValidation:
    """Run C01 (read-only), C02 (table allowlist) and C03 (row limit) on BigQuery SQL."""
    root, failure = _parse_select_only(sql)
    if root is None:
        reason = failure or "parse_error"
        c01_failed = CheckResult(id="C01_select_only", passed=False, detail=reason)
        return _blocked(sql, (c01_failed,), reason)
    c01 = CheckResult(id="C01_select_only", passed=True)
    table_failure = _table_violation(root)
    if table_failure is not None:
        c02_failed = CheckResult(id="C02_allowed_tables", passed=False, detail=table_failure)
        return _blocked(sql, (c01, c02_failed), table_failure)
    c02 = CheckResult(id="C02_allowed_tables", passed=True)
    final_sql, c03 = _apply_limit(root)
    return SqlValidation(is_valid=True, sql=final_sql, checks=(c01, c02, c03), reason=None)
