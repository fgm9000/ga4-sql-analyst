from __future__ import annotations

from pathlib import Path

import pytest

from spikes.transpile import connect_sample, rewrite_for_duckdb

PARQUET = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "ga4_sample.parquet"

QUERIES: dict[str, str] = {
    "Q1_canal_receita": (
        "SELECT traffic_source.medium AS canal, "
        "SUM(ecommerce.purchase_revenue_in_usd) AS receita "
        "FROM `bigquery-public-data.ga4_obfuscated_sample_ecommerce.events_*`"
        " WHERE _TABLE_SUFFIX BETWEEN '20210102' AND '20210131' "
        "GROUP BY canal ORDER BY receita DESC LIMIT 100"
    ),
    "Q2_funil_device": (
        "SELECT device.category AS dispositivo, "
        "COUNTIF(event_name = 'view_item') AS views, "
        "COUNTIF(event_name = 'add_to_cart') AS carts, "
        "COUNTIF(event_name = 'purchase') AS compras, "
        "SAFE_DIVIDE(COUNTIF(event_name = 'purchase'), "
        "COUNTIF(event_name = 'view_item')) AS conversao "
        "FROM `bigquery-public-data.ga4_obfuscated_sample_ecommerce.events_*`"
        " GROUP BY dispositivo LIMIT 100"
    ),
    "Q3_unnest_correlacionado": (
        "SELECT COUNT(DISTINCT CONCAT(user_pseudo_id, CAST((SELECT value.int_value "
        "FROM UNNEST(event_params) WHERE key = 'ga_session_id') AS STRING))) AS sessoes "
        "FROM `bigquery-public-data.ga4_obfuscated_sample_ecommerce.events_*`"
        " WHERE _TABLE_SUFFIX BETWEEN '20210102' AND '20210131'"
    ),
    "Q4_cross_join_unnest": (
        "SELECT ep.key, COUNT(*) AS n "
        "FROM `bigquery-public-data.ga4_obfuscated_sample_ecommerce.events_*`"
        ", UNNEST(event_params) AS ep "
        "WHERE _TABLE_SUFFIX BETWEEN '20210125' AND '20210131' "
        "GROUP BY ep.key ORDER BY n DESC LIMIT 100"
    ),
}


def _check(condition: bool, message: str) -> None:
    if not condition:
        pytest.fail(message)


@pytest.mark.parametrize("name", list(QUERIES))
def test_query_runs_on_duckdb(name: str) -> None:
    duck_sql = rewrite_for_duckdb(QUERIES[name])
    _check("events_*" not in duck_sql, f"curinga permaneceu: {duck_sql}")
    _check("_TABLE_SUFFIX" not in duck_sql.upper(), f"_TABLE_SUFFIX permaneceu: {duck_sql}")
    con = connect_sample(PARQUET)
    rows = con.execute(duck_sql).fetchall()
    _check(len(rows) >= 1, f"{name}: 0 linhas; SQL={duck_sql}")
