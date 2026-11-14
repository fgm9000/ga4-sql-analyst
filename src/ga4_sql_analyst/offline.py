"""Offline mode: DuckDB over the local Parquet sample plus a deterministic FunctionModel."""

import json
import re
from pathlib import Path

from pydantic_ai import models
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    ToolCallPart,
    UserPromptPart,
)
from pydantic_ai.models.function import AgentInfo, FunctionModel

from ga4_sql_analyst.llm import PydanticAiSqlGenerator, PydanticAiSummarizer
from ga4_sql_analyst.models import Lang
from ga4_sql_analyst.scenarios import SCENARIOS
from ga4_sql_analyst.service import AskService
from ga4_sql_analyst.snapshot import Snapshot
from ga4_sql_analyst.warehouse import DuckDbWarehouse

RESULT_PATTERN = re.compile(r"<query_result>(.*)</query_result>", re.DOTALL)
SUMMARY_TEXT: dict[Lang, str] = {
    "pt": "Resultado principal: {key} = {value}.",
    "en": "Top result: {key} = {value}.",
}
EMPTY_TEXT: dict[Lang, str] = {"pt": "Nenhum resultado encontrado.", "en": "No results found."}
DEFAULT_OFFLINE_SQL = (
    "SELECT event_name, COUNT(*) AS n "
    "FROM `bigquery-public-data.ga4_obfuscated_sample_ecommerce.events_*` "
    "GROUP BY event_name ORDER BY n DESC LIMIT 10"
)
OFFLINE_INTENT = "offline demo"
OFFLINE_TABLES = ["events_*"]
PORTUGUESE_MARKER = "português"


def _prompt_text(messages: list[ModelMessage]) -> str:
    return "\n".join(
        str(part.content)
        for message in messages
        if isinstance(message, ModelRequest)
        for part in message.parts
        if isinstance(part, UserPromptPart)
    )


def _scenario_sql(prompt: str) -> str:
    """Return the scenario SQL whose question appears in the prompt, else the demo default."""
    for scenario in SCENARIOS:
        if any(question in prompt for question in scenario.question.values()):
            return scenario.offline_sql
    return DEFAULT_OFFLINE_SQL


def _summary_text(prompt: str, lang: Lang) -> str:
    match = RESULT_PATTERN.search(prompt)
    rows = json.loads(match.group(1)) if match is not None else []
    if not rows:
        return EMPTY_TEXT[lang]
    key, value = next(iter(rows[0].items()))
    return SUMMARY_TEXT[lang].format(key=key, value=value)


def _offline_handler(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
    prompt = _prompt_text(messages)
    lang: Lang = "pt" if PORTUGUESE_MARKER in (info.instructions or "") else "en"
    args: dict[str, str | list[str]]
    if "<query_result>" in prompt:
        args = {"summary": _summary_text(prompt, lang)}
    else:
        args = {"sql": _scenario_sql(prompt), "tables": OFFLINE_TABLES, "intent": OFFLINE_INTENT}
    return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, json.dumps(args))])


def build_offline_model() -> FunctionModel:
    """Build the deterministic model that answers the four scenarios without any network."""
    return FunctionModel(_offline_handler)


def build_offline_service(sample_path: Path, max_bytes: int) -> AskService:
    """Build an AskService on the local Parquet sample; real model requests are disabled."""
    models.ALLOW_MODEL_REQUESTS = False
    model = build_offline_model()
    return AskService(
        PydanticAiSqlGenerator(model),
        PydanticAiSummarizer(model),
        DuckDbWarehouse(sample_path),
        Snapshot([]),
        max_bytes,
    )
