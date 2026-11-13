from __future__ import annotations

from pathlib import Path

import duckdb
import sqlglot
from sqlglot import exp

SOURCE_WILDCARD = "bigquery-public-data.ga4_obfuscated_sample_ecommerce.events_*"
LOCAL_TABLE = "events"


def _is_wildcard(table: exp.Table) -> bool:
    parts = [p.name for p in table.parts]
    return ".".join(parts) == SOURCE_WILDCARD or table.name == SOURCE_WILDCARD


def _rewrite_node(node: exp.Expression) -> exp.Expression:
    if isinstance(node, exp.Table) and _is_wildcard(node):
        return exp.to_table(LOCAL_TABLE)
    if isinstance(node, exp.Column) and node.name.upper() == "_TABLE_SUFFIX":
        return exp.column("event_date", table=node.table or None)
    if isinstance(node, exp.Unnest) and isinstance(node.parent, exp.From) and not node.alias:
        # DuckDB devolve o STRUCT inteiro em uma coluna "unnest"; BigQuery expoe os campos.
        # max_depth := 2 (so valido na lista do SELECT) abre a lista e um nivel do STRUCT.
        call = exp.Anonymous(
            this="UNNEST",
            expressions=[
                node.expressions[0],
                exp.PropertyEQ(
                    this=exp.to_identifier("max_depth"), expression=exp.Literal.number(2)
                ),
            ],
        )
        return exp.Subquery(this=exp.select(call))
    return node


def rewrite_for_duckdb(bigquery_sql: str) -> str:
    tree = sqlglot.parse_one(bigquery_sql, read="bigquery")
    return tree.transform(_rewrite_node).sql(dialect="duckdb")


def connect_sample(parquet_path: Path) -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    con.read_parquet(str(parquet_path)).create_view(LOCAL_TABLE)
    return con
