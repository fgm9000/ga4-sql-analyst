"""Tests for C01-C03 (validate_sql) and rewrite_for_duckdb."""

from pathlib import Path

import duckdb
import pytest
from sqlglot import exp

import ga4_sql_analyst.sql_rules as sql_rules
from ga4_sql_analyst.domain import MAX_ROWS, rewrite_for_duckdb, validate_sql

PARQUET = Path(__file__).parent / "fixtures" / "ga4_sample.parquet"
DATASET = "bigquery-public-data.ga4_obfuscated_sample_ecommerce"
TABLE = "`bigquery-public-data.ga4_obfuscated_sample_ecommerce.events_*`"
DAILY = "`bigquery-public-data.ga4_obfuscated_sample_ecommerce.events_20210131`"
INFO_SCHEMA = "`bigquery-public-data.ga4_obfuscated_sample_ecommerce.INFORMATION_SCHEMA.TABLES`"
CHECK_IDS = ["C01_select_only", "C02_allowed_tables", "C03_limit"]
NON_SELECT = {"forbidden_statement", "not_select"}

SPIKE_QUERIES: dict[str, str] = {
    "channel_revenue": (
        "SELECT traffic_source.medium AS canal, "
        "SUM(ecommerce.purchase_revenue_in_usd) AS receita "
        "FROM <T> WHERE _TABLE_SUFFIX BETWEEN '20210102' AND '20210131' "
        "GROUP BY canal ORDER BY receita DESC LIMIT 100"
    ),
    "device_funnel": (
        "SELECT device.category AS dispositivo, "
        "COUNTIF(event_name = 'view_item') AS views, "
        "COUNTIF(event_name = 'add_to_cart') AS carts, "
        "COUNTIF(event_name = 'purchase') AS compras, "
        "SAFE_DIVIDE(COUNTIF(event_name = 'purchase'), "
        "COUNTIF(event_name = 'view_item')) AS conversao "
        "FROM <T> GROUP BY dispositivo LIMIT 100"
    ),
    "correlated_unnest": (
        "SELECT COUNT(DISTINCT CONCAT(user_pseudo_id, CAST((SELECT value.int_value "
        "FROM UNNEST(event_params) WHERE key = 'ga_session_id') AS STRING))) AS sessoes "
        "FROM <T> WHERE _TABLE_SUFFIX BETWEEN '20210102' AND '20210131'"
    ),
    "cross_join_unnest": (
        "SELECT ep.key, COUNT(*) AS n FROM <T>, UNNEST(event_params) AS ep "
        "WHERE _TABLE_SUFFIX BETWEEN '20210125' AND '20210131' "
        "GROUP BY ep.key ORDER BY n DESC LIMIT 100"
    ),
}


def _q(template: str) -> str:
    """Expand table placeholders (keeps SQL literals free of string interpolation)."""
    return (
        template.replace("<T>", TABLE)
        .replace("<D>", DAILY)
        .replace("<I>", INFO_SCHEMA)
        .replace("<DS>", DATASET)
    )


def test_valid_select_runs_all_three_checks() -> None:
    result = validate_sql(_q("SELECT event_name FROM <T>"))
    assert result.is_valid
    assert result.reason is None
    assert [check.id for check in result.checks] == CHECK_IDS
    assert all(check.passed for check in result.checks)
    assert result.checks[2].detail == "limit_injected"
    assert result.sql.endswith(f"LIMIT {MAX_ROWS}")


@pytest.mark.parametrize(
    ("sql", "expected"),
    [
        (_q("DELETE FROM <T> WHERE true"), NON_SELECT),
        ("DROP TABLE x", NON_SELECT),
        ("SELECT 1; DROP TABLE x", {"multiple_statements"}),
        (_q("INSERT INTO x SELECT * FROM <T>"), NON_SELECT),
        (_q("CREATE TABLE x AS SELECT * FROM <T>"), NON_SELECT),
        (_q("MERGE INTO x USING <T> AS s ON x.a = s.a WHEN MATCHED THEN DELETE"), NON_SELECT),
        ("", {"parse_error", "not_select"}),
        ("not sql at all ;;", {"parse_error", "not_select"}),
        ("DECLARE x INT64; SELECT 1", {"multiple_statements", "parse_error"}),
        ("(SELECT 1)", {"not_select"}),
    ],
)
def test_c01_blocks_non_select(sql: str, expected: set[str]) -> None:
    result = validate_sql(sql)
    assert not result.is_valid
    assert result.sql == sql
    assert result.reason in expected
    assert [check.id for check in result.checks] == CHECK_IDS
    assert result.checks[0].passed is False
    assert result.checks[0].detail == result.reason
    for pending in result.checks[1:]:
        assert pending.passed is False
        assert pending.detail == "not_evaluated"


def test_c01_rejects_forbidden_node_inside_select_root(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sql_rules, "FORBIDDEN_TYPES", (exp.Literal,))
    result = validate_sql("SELECT 1")
    assert result.reason == "forbidden_statement"


def test_c01_deeply_nested_sql_is_parse_error() -> None:
    result = validate_sql("SELECT " + "(" * 5000 + "1" + ")" * 5000)
    assert not result.is_valid
    assert result.reason == "parse_error"


@pytest.mark.parametrize(
    ("sql", "name"),
    [
        ("SELECT * FROM `other-project.ds.t`", "other-project.ds.t"),
        (_q("SELECT * FROM <I>"), "INFORMATION_SCHEMA.TABLES"),
        ("SELECT * FROM events_*", "events_*"),
        ("SELECT * FROM `ga4_obfuscated_sample_ecommerce.events_*`", "events_*"),
        (_q("SELECT * FROM <T> WHERE x IN (SELECT x FROM `a.b.c`)"), "a.b.c"),
        (_q("SELECT 1 FROM <T> UNION ALL SELECT 1 FROM `a.b.c`"), "a.b.c"),
        (_q("WITH t AS (SELECT 1 FROM `a.b.c`) SELECT * FROM t, <T>"), "a.b.c"),
        (_q("SELECT * FROM `<DS>.events_2021`"), "events_2021"),
    ],
)
def test_c02_blocks_disallowed_tables(sql: str, name: str) -> None:
    result = validate_sql(sql)
    assert not result.is_valid
    assert result.reason is not None
    assert result.reason.startswith("table_not_allowed:")
    assert result.reason.endswith(name)
    assert result.checks[0].passed is True
    assert result.checks[1].passed is False
    assert result.checks[1].detail == result.reason
    assert result.checks[2].detail == "not_evaluated"


def test_cte_is_allowed() -> None:
    result = validate_sql(_q("WITH t AS (SELECT event_name FROM <T>) SELECT * FROM t"))
    assert result.is_valid
    assert result.checks[1].passed is True


def test_cte_name_does_not_whitelist_qualified_table() -> None:
    sql = _q("WITH t AS (SELECT 1) SELECT * FROM `other.ds.t`, <T>")
    assert validate_sql(sql).reason == "table_not_allowed:other.ds.t"


def test_daily_table_is_allowed() -> None:
    assert validate_sql(_q("SELECT 1 FROM <D>")).is_valid


def test_comment_with_forbidden_words_is_ignored() -> None:
    sql = _q("SELECT event_name /* DROP TABLE x */ FROM <T> -- DELETE FROM y\nLIMIT 5")
    result = validate_sql(sql)
    assert result.is_valid
    assert result.checks[2].detail is None


def test_mixed_case_keywords_and_names() -> None:
    mixed = _q("sElEcT event_name FrOm `<DS>.EVENTS_*`").upper().replace("SELECT", "sElEcT")
    assert validate_sql(mixed).is_valid
    assert validate_sql(_q("select event_name from <T>")).is_valid
    assert validate_sql("dRoP tAbLe x").reason in NON_SELECT
    assert validate_sql("SELECT 1; dElEtE FROM x").reason == "multiple_statements"


def test_limit_above_cap_is_replaced() -> None:
    result = validate_sql(_q("SELECT event_name FROM <T> LIMIT 5000"))
    assert result.is_valid
    assert result.checks[2].passed is True
    assert result.checks[2].detail == "limit_capped"
    assert result.sql.endswith("LIMIT 100")
    assert "5000" not in result.sql


def test_limit_within_cap_is_kept() -> None:
    result = validate_sql(_q("SELECT event_name FROM <T> LIMIT 100"))
    assert result.checks[2].detail is None
    assert result.sql.endswith("LIMIT 100")


@pytest.mark.parametrize("limit", ["@n", "1 + 1", "-5", "1.5"])
def test_non_literal_limit_is_capped(limit: str) -> None:
    result = validate_sql(_q("SELECT event_name FROM <T> LIMIT ") + limit)
    assert result.is_valid
    assert result.checks[2].detail == "limit_capped"
    assert result.sql.endswith("LIMIT 100")


def test_union_gets_limit_on_outer_query() -> None:
    sql = _q("SELECT event_name FROM <T> UNION ALL SELECT event_name FROM <T>")
    result = validate_sql(sql)
    assert result.is_valid
    assert result.checks[2].detail == "limit_injected"
    assert result.sql.endswith("LIMIT 100")


def test_inner_limit_does_not_count_as_outer_limit() -> None:
    sql = _q("SELECT * FROM (SELECT event_name FROM <T> LIMIT 5)")
    assert validate_sql(sql).checks[2].detail == "limit_injected"


@pytest.mark.parametrize("name", list(SPIKE_QUERIES))
def test_rewrite_for_duckdb_runs_spike_queries(name: str) -> None:
    duck_sql = rewrite_for_duckdb(_q(SPIKE_QUERIES[name]))
    assert "events_*" not in duck_sql
    assert "_TABLE_SUFFIX" not in duck_sql.upper()
    con = duckdb.connect()
    con.read_parquet(str(PARQUET)).create_view("events")
    assert len(con.execute(duck_sql).fetchall()) >= 1


def test_rewrite_maps_daily_table_and_keeps_alias() -> None:
    duck_sql = rewrite_for_duckdb(_q("SELECT e.event_name FROM <D> AS e"))
    assert "events_2021" not in duck_sql
    assert "events AS e" in duck_sql


def test_rewrite_does_not_touch_cte_reference() -> None:
    duck_sql = rewrite_for_duckdb(_q("WITH t AS (SELECT 1 AS a FROM <T>) SELECT a FROM t"))
    assert "FROM t" in duck_sql


@pytest.mark.parametrize(
    ("sql", "detail"),
    [
        ("SELECT SESSION_USER()", "forbidden_function:SESSION_USER"),
        ("SELECT session_user() FROM <T>", "forbidden_function:SESSION_USER"),
        ("SELECT CURRENT_USER()", "forbidden_function:CURRENT_USER"),
        ("SELECT EXTERNAL_QUERY('c', 'select 1')", "forbidden_function:EXTERNAL_QUERY"),
        ("SELECT EXTERNAL_OBJECT_TRANSFORM(t, ['x']) FROM <T>", "forbidden_function"),
        ("SELECT * FROM ML.PREDICT(MODEL m, (SELECT 1))", "forbidden_function:ML.PREDICT"),
        ("SELECT * FROM VECTOR_SEARCH(a, 'b', c)", "forbidden_function:VECTOR_SEARCH"),
        ("SELECT AI.GENERATE('x') FROM <T>", "forbidden_function:AI."),
        ("SELECT KEYS.NEW_KEYSET('x') FROM <T>", "forbidden_function:KEYS.NEW_KEYSET"),
        ("SELECT AEAD.ENCRYPT(1, 2, 3) FROM <T>", "forbidden_function:AEAD.ENCRYPT"),
        ("SELECT DETERMINISTIC_ENCRYPT(1, 2, 3) FROM <T>", "forbidden_function:DETERMINISTIC_E"),
        ("SELECT DETERMINISTIC_DECRYPT(1, 2, 3) FROM <T>", "forbidden_function:DETERMINISTIC_D"),
        ("SELECT @@project_id", "forbidden_function:@@project_id"),
        ("SELECT @@project_id FROM <T>", "forbidden_function:@@project_id"),
        ("SELECT * FROM <T> WHERE x IN (SELECT SESSION_USER())", "forbidden_function:SESSION_USER"),
        ("WITH t AS (SELECT CURRENT_USER() AS u) SELECT * FROM t, <T>", "forbidden_function:CURR"),
    ],
)
def test_c01_blocks_identity_and_environment_functions(sql: str, detail: str) -> None:
    result = validate_sql(_q(sql))
    assert not result.is_valid
    assert result.reason is not None
    assert result.reason.startswith(detail)
    assert result.checks[0].passed is False
    assert result.checks[0].detail == result.reason
    assert result.checks[1].detail == "not_evaluated"


@pytest.mark.parametrize(
    "sql",
    ["SELECT 1", "SELECT CURRENT_DATE()", "WITH t AS (SELECT 1) SELECT * FROM t"],
)
def test_c02_requires_at_least_one_allowed_table(sql: str) -> None:
    result = validate_sql(sql)
    assert not result.is_valid
    assert result.reason == "no_allowed_table"
    assert result.checks[0].passed is True
    assert result.checks[1].passed is False
    assert result.checks[1].detail == "no_allowed_table"
    assert result.checks[2].detail == "not_evaluated"
