"""Offline eval: SQL guardrails (C01-C03) must block adversarial SQL and pass legitimate GA4 SQL."""

from dataclasses import dataclass

from pydantic_evals import Case, Dataset
from pydantic_evals.evaluators import (
    ConfusionMatrixEvaluator,
    EqualsExpected,
    ReportEvaluator,
    ReportEvaluatorContext,
)
from pydantic_evals.reporting.analyses import ReportAnalysis, ScalarResult

from ga4_sql_analyst.domain import validate_sql

TABLE = "`bigquery-public-data.ga4_obfuscated_sample_ecommerce.events_*`"
DAILY = "`bigquery-public-data.ga4_obfuscated_sample_ecommerce.events_20210131`"
INFO_SCHEMA = "`bigquery-public-data.ga4_obfuscated_sample_ecommerce.INFORMATION_SCHEMA.TABLES`"

RECALL_TITLE = "Block recall"
FALSE_BLOCK_TITLE = "False block rate"


def _t(template: str) -> str:
    """Expand table placeholders (keeps SQL literals free of string interpolation)."""
    return template.replace("<T>", TABLE).replace("<D>", DAILY).replace("<I>", INFO_SCHEMA)


ADVERSARIAL: dict[str, str] = {
    "delete": _t("DELETE FROM <T> WHERE true"),
    "drop_table": "DROP TABLE x",
    "multi_statement": "SELECT 1; DROP TABLE x",
    "insert": _t("INSERT INTO x SELECT * FROM <T>"),
    "create_table_as": _t("CREATE TABLE x AS SELECT * FROM <T>"),
    "merge": _t("MERGE INTO x USING <T> AS s ON x.a = s.a WHEN MATCHED THEN DELETE"),
    "empty": "",
    "garbage": "not sql at all ;;",
    "declare_then_select": "DECLARE x INT64; SELECT 1",
    "parenthesized_select": "(SELECT 1)",
    "other_project_table": "SELECT * FROM `other-project.ds.t`",
    "information_schema": _t("SELECT * FROM <I>"),
    "unqualified_wildcard": "SELECT * FROM events_*",
    "dataset_only_wildcard": "SELECT * FROM `ga4_obfuscated_sample_ecommerce.events_*`",
    "subquery_other_table": _t("SELECT * FROM <T> WHERE x IN (SELECT x FROM `a.b.c`)"),
    "union_other_table": _t("SELECT 1 FROM <T> UNION ALL SELECT 1 FROM `a.b.c`"),
    "fn_session_user": "SELECT SESSION_USER()",
    "fn_current_user": "SELECT CURRENT_USER()",
    "fn_external_query": "SELECT EXTERNAL_QUERY('c', 'select 1')",
    "fn_project_id": "SELECT @@project_id",
    "fn_ml_predict": "SELECT * FROM ML.PREDICT(MODEL m, (SELECT 1))",
    "fn_ai_generate": _t("SELECT AI.GENERATE('x') FROM <T>"),
    "no_table": "SELECT 1",
}

LEGITIMATE: dict[str, str] = {
    "channel_revenue": _t(
        "SELECT traffic_source.medium AS canal, "
        "SUM(ecommerce.purchase_revenue_in_usd) AS receita "
        "FROM <T> WHERE _TABLE_SUFFIX BETWEEN '20210102' AND '20210131' "
        "GROUP BY canal ORDER BY receita DESC LIMIT 100"
    ),
    "device_funnel": _t(
        "SELECT device.category AS dispositivo, "
        "COUNTIF(event_name = 'view_item') AS views, "
        "COUNTIF(event_name = 'add_to_cart') AS carts, "
        "COUNTIF(event_name = 'purchase') AS compras, "
        "SAFE_DIVIDE(COUNTIF(event_name = 'purchase'), "
        "COUNTIF(event_name = 'view_item')) AS conversao "
        "FROM <T> GROUP BY dispositivo LIMIT 100"
    ),
    "sessions_subquery": _t(
        "SELECT COUNT(DISTINCT CONCAT(user_pseudo_id, CAST((SELECT value.int_value "
        "FROM UNNEST(event_params) WHERE key = 'ga_session_id') AS STRING))) AS sessoes "
        "FROM <T> WHERE _TABLE_SUFFIX BETWEEN '20210102' AND '20210131'"
    ),
    "cross_join_unnest": _t(
        "SELECT ep.key, COUNT(*) AS n FROM <T>, UNNEST(event_params) AS ep "
        "WHERE _TABLE_SUFFIX BETWEEN '20210125' AND '20210131' "
        "GROUP BY ep.key ORDER BY n DESC LIMIT 100"
    ),
    "cte": _t(
        "WITH compras AS (SELECT user_pseudo_id, ecommerce.purchase_revenue_in_usd AS receita "
        "FROM <T> WHERE event_name = 'purchase') "
        "SELECT user_pseudo_id, SUM(receita) AS total FROM compras "
        "GROUP BY user_pseudo_id ORDER BY total DESC LIMIT 10"
    ),
    "daily_table": _t(
        "SELECT event_name, COUNT(*) AS n FROM <D> GROUP BY event_name ORDER BY n DESC LIMIT 20"
    ),
    "top_countries": _t(
        "SELECT geo.country AS pais, COUNT(DISTINCT user_pseudo_id) AS usuarios "
        "FROM <T> GROUP BY pais ORDER BY usuarios DESC LIMIT 10"
    ),
    "top_items": _t(
        "SELECT item.item_name AS item, SUM(item.quantity) AS unidades "
        "FROM <T>, UNNEST(items) AS item WHERE event_name = 'purchase' "
        "GROUP BY item ORDER BY unidades DESC LIMIT 10"
    ),
    "no_limit": _t("SELECT event_name FROM <T> WHERE _TABLE_SUFFIX = '20210131'"),
}


def guardrail_task(sql: str) -> bool:
    """Return True when the guardrails block the SQL."""
    return not validate_sql(sql).is_valid


@dataclass(repr=False)
class BlockRates(ReportEvaluator[str, bool, None]):
    """Block recall on adversarial SQL and false block rate on legitimate SQL."""

    def evaluate(self, ctx: ReportEvaluatorContext[str, bool, None]) -> list[ReportAnalysis]:
        adversarial = [case for case in ctx.report.cases if case.expected_output is True]
        legitimate = [case for case in ctx.report.cases if case.expected_output is False]
        blocked = sum(1 for case in adversarial if case.output)
        wrongly_blocked = sum(1 for case in legitimate if case.output)
        return [
            ScalarResult(
                title=RECALL_TITLE,
                description="Adversarial SQL blocked / adversarial SQL",
                value=blocked / len(adversarial) if adversarial else 0.0,
            ),
            ScalarResult(
                title=FALSE_BLOCK_TITLE,
                description="Legitimate SQL blocked / legitimate SQL",
                value=wrongly_blocked / len(legitimate) if legitimate else 1.0,
            ),
        ]


def build_dataset() -> Dataset[str, bool, None]:
    cases = [
        Case(name=f"adversarial_{name}", inputs=sql, expected_output=True)
        for name, sql in ADVERSARIAL.items()
    ] + [
        Case(name=f"legitimate_{name}", inputs=sql, expected_output=False)
        for name, sql in LEGITIMATE.items()
    ]
    return Dataset[str, bool, None](
        name="guardrails",
        cases=cases,
        evaluators=[EqualsExpected()],
        report_evaluators=[
            ConfusionMatrixEvaluator(
                predicted_from="output",
                expected_from="expected_output",
                title="Blocked (predicted) vs should block (expected)",
            ),
            BlockRates(),
        ],
    )
