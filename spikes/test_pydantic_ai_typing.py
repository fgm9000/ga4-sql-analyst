from __future__ import annotations

import json

import pytest
from pydantic_ai import models
from pydantic_ai.exceptions import UnexpectedModelBehavior
from pydantic_ai.messages import ModelMessage, ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from spikes.pydantic_ai_typing import build_sql_agent

models.ALLOW_MODEL_REQUESTS = False


def _reply(info: AgentInfo, sql: str) -> ModelResponse:
    args = json.dumps({"sql": sql, "tables": ["t"], "intent": "demo"})
    return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, args)])


def _check(condition: bool, message: str) -> None:
    if not condition:
        pytest.fail(message)


def test_valid_sql_first_call() -> None:
    def fn(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        return _reply(info, "SELECT 1")

    agent = build_sql_agent(FunctionModel(fn))
    result = agent.run_sync("quero algo")
    _check(result.output.sql.startswith("SELECT"), "esperava SELECT")


def test_retry_after_delete() -> None:
    calls: list[int] = []

    def fn(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        calls.append(1)
        return _reply(info, "DELETE FROM x" if len(calls) == 1 else "SELECT 1")

    agent = build_sql_agent(FunctionModel(fn))
    result = agent.run_sync("quero algo")
    _check(result.output.sql == "SELECT 1", "saida final deveria ser SELECT")
    _check(len(calls) == 2, f"esperava 2 chamadas, houve {len(calls)}")


def test_retries_exhausted() -> None:
    def fn(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        return _reply(info, "DELETE FROM x")

    agent = build_sql_agent(FunctionModel(fn))
    with pytest.raises(UnexpectedModelBehavior):
        agent.run_sync("quero algo")
