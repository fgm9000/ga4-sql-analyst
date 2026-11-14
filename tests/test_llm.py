from __future__ import annotations

import json
from collections.abc import Callable

import httpx
import pytest
from pydantic_ai import models
from pydantic_ai.exceptions import ModelHTTPError
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from ga4_sql_analyst.errors import LlmUnavailableError, SqlRejectedError
from ga4_sql_analyst.llm import (
    PydanticAiSqlGenerator,
    PydanticAiSummarizer,
    SummaryDraft,
    build_vertex_model,
)
from ga4_sql_analyst.ports import Row

models.ALLOW_MODEL_REQUESTS = False

VALID_SQL = (
    "SELECT event_name FROM `bigquery-public-data.ga4_obfuscated_sample_ecommerce.events_*` "
    "WHERE _TABLE_SUFFIX BETWEEN '20210101' AND '20210131'"
)
DELETE_SQL = (
    "DELETE FROM `bigquery-public-data.ga4_obfuscated_sample_ecommerce.events_*` WHERE true"
)
Handler = Callable[[list[ModelMessage], AgentInfo], ModelResponse]


def _sql_reply(info: AgentInfo, sql: str) -> ModelResponse:
    args = json.dumps({"sql": sql, "tables": ["events_*"], "intent": "demo"})
    return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, args)])


def _summary_reply(info: AgentInfo, text: str) -> ModelResponse:
    args = json.dumps({"summary": text})
    return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, args)])


def _sql_generator(handler: Handler) -> PydanticAiSqlGenerator:
    return PydanticAiSqlGenerator(FunctionModel(handler))


def _raising(error: Exception) -> Handler:
    def handler(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        raise error

    return handler


@pytest.mark.anyio
async def test_valid_sql_first_call_gets_limit() -> None:
    def handler(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        return _sql_reply(info, VALID_SQL)

    draft = await _sql_generator(handler).generate("sessions", "en", None)
    assert draft.sql.endswith("LIMIT 100")
    assert draft.intent == "demo"


@pytest.mark.anyio
async def test_invalid_then_valid_retries_once() -> None:
    calls: list[int] = []
    instructions: list[str | None] = []

    def handler(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        calls.append(1)
        instructions.append(info.instructions)
        sql = DELETE_SQL if len(calls) == 1 else VALID_SQL
        return _sql_reply(info, sql)

    draft = await _sql_generator(handler).generate("sessions", "pt", None)
    assert len(calls) == 2
    assert draft.sql.endswith("LIMIT 100")
    assert instructions[0] is not None
    assert "analista de dados" in instructions[0]


@pytest.mark.anyio
async def test_english_instructions_are_selected() -> None:
    seen: list[str | None] = []

    def handler(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        seen.append(info.instructions)
        return _sql_reply(info, VALID_SQL)

    await _sql_generator(handler).generate("sessions", "en", None)
    assert seen[0] is not None
    assert "data analyst" in seen[0]


@pytest.mark.anyio
async def test_always_invalid_raises_sql_rejected() -> None:
    def handler(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        return _sql_reply(info, DELETE_SQL)

    with pytest.raises(SqlRejectedError) as raised:
        await _sql_generator(handler).generate("sessions", "en", None)
    assert raised.value.detail == "not_select"


@pytest.mark.anyio
async def test_rejection_keeps_detail_with_colon() -> None:
    def handler(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        return _sql_reply(info, "SELECT a FROM `other-project.ds.events_*`")

    with pytest.raises(SqlRejectedError) as raised:
        await _sql_generator(handler).generate("sessions", "en", None)
    assert raised.value.detail.startswith("table_not_allowed:")


@pytest.mark.anyio
async def test_model_http_error_is_unavailable() -> None:
    handler = _raising(ModelHTTPError(status_code=503, model_name="fake"))
    with pytest.raises(LlmUnavailableError):
        await _sql_generator(handler).generate("sessions", "en", None)


@pytest.mark.anyio
async def test_httpx_error_is_unavailable() -> None:
    handler = _raising(httpx.ConnectError("boom"))
    with pytest.raises(LlmUnavailableError):
        await _sql_generator(handler).generate("sessions", "en", None)


@pytest.mark.anyio
async def test_timeout_is_unavailable() -> None:
    with pytest.raises(LlmUnavailableError):
        await _sql_generator(_raising(TimeoutError("slow"))).generate("sessions", "en", None)


@pytest.mark.anyio
async def test_unstructured_output_is_unavailable() -> None:
    def handler(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        return ModelResponse(parts=[TextPart("not a tool call")])

    with pytest.raises(LlmUnavailableError):
        await _sql_generator(handler).generate("sessions", "en", None)


@pytest.mark.anyio
async def test_summarizer_happy_path() -> None:
    prompts: list[str] = []

    def handler(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        prompts.append(str(messages))
        return _summary_reply(info, "There were 3 sessions.")

    rows: list[Row] = [{"sessions": 3}]
    summarizer = PydanticAiSummarizer(FunctionModel(handler))
    summary = await summarizer.summarize("how many?", "en", "SELECT 1", rows)
    assert summary == "There were 3 sessions."
    assert '"sessions": 3' in prompts[0]


@pytest.mark.anyio
async def test_summarizer_provider_error_is_unavailable() -> None:
    summarizer = PydanticAiSummarizer(FunctionModel(_raising(TimeoutError("slow"))))
    with pytest.raises(LlmUnavailableError):
        await summarizer.summarize("how many?", "pt", "SELECT 1", [])


def test_summary_draft_is_frozen() -> None:
    draft = SummaryDraft(summary="ok")
    with pytest.raises(ValueError):
        draft.summary = "changed"


def test_build_vertex_model_does_not_touch_network(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "demo-project")
    model = build_vertex_model("gemini-2.5-flash", "demo-project", "us-central1")
    assert model.model_name == "gemini-2.5-flash"
