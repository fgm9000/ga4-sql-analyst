"""Spike: PydanticAI 2.68.0 sob `mypy --strict` sem supressoes.

Funcionou: `Agent[None, SqlDraft](model, output_type=SqlDraft)` + `@agent.output_validator`
sincrono com `(ctx: RunContext[None], output: SqlDraft) -> SqlDraft`.
Apenas esta forma foi testada (passou de primeira); o unico erro foi de modulo duplicado
("Source file found twice"), resolvido com `spikes/__init__.py`.
"""

from __future__ import annotations

from pydantic import BaseModel
from pydantic_ai import Agent, ModelRetry, RunContext
from pydantic_ai.models import Model
from pydantic_ai.models.google import GoogleModel
from pydantic_ai.providers.google_cloud import GoogleCloudProvider


class SqlDraft(BaseModel):
    sql: str
    tables: list[str]
    intent: str


def is_select_only(sql: str) -> bool:
    """Dubles ingenuo da regra real: so SELECT, sem ';' no meio."""
    text = sql.strip().upper()
    if not text.startswith("SELECT"):
        return False
    return ";" not in text.rstrip(";")


def build_sql_agent(model: Model) -> Agent[None, SqlDraft]:
    agent = Agent[None, SqlDraft](model, output_type=SqlDraft)

    @agent.output_validator
    def _validate(ctx: RunContext[None], output: SqlDraft) -> SqlDraft:
        if not is_select_only(output.sql):
            raise ModelRetry("A consulta deve ser somente SELECT, sem multiplos comandos.")
        return output

    return agent


def build_vertex_model(model_id: str, project: str, location: str) -> GoogleModel:
    return GoogleModel(model_id, provider=GoogleCloudProvider(project=project, location=location))
