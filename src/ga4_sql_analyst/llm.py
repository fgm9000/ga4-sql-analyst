"""PydanticAI adapters implementing the SqlGenerator and Summarizer ports."""

from collections.abc import Sequence

import httpx
from pydantic import BaseModel, ConfigDict, Field
from pydantic_ai import Agent, ModelRetry, RunContext
from pydantic_ai.exceptions import ModelHTTPError, UnexpectedModelBehavior
from pydantic_ai.models import Model
from pydantic_ai.models.google import GoogleModel
from pydantic_ai.providers.google_cloud import GoogleCloudProvider
from pydantic_ai.settings import ModelSettings

from ga4_sql_analyst.domain import validate_sql
from ga4_sql_analyst.errors import LlmUnavailableError, SqlRejectedError
from ga4_sql_analyst.models import Lang, Period, SqlDraft
from ga4_sql_analyst.ports import Row
from ga4_sql_analyst.prompt import (
    SQL_INSTRUCTIONS,
    SUMMARY_INSTRUCTIONS,
    build_sql_prompt,
    build_summary_prompt,
)

SQL_OUTPUT_RETRIES = 1
SQL_MAX_OUTPUT_TOKENS = 800
SQL_TEMPERATURE = 0.0
SUMMARY_MAX_OUTPUT_TOKENS = 400
SUMMARY_TEMPERATURE = 0.2
SUMMARY_MAX_CHARS = 1200
RETRY_DETAIL_SEPARATOR = ": "

RULE_EXPLANATION = "Only one read-only SELECT on the allowed GA4 events_* table is accepted."

_PROVIDER_ERRORS = (UnexpectedModelBehavior, ModelHTTPError, httpx.HTTPError, TimeoutError)


class SummaryDraft(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    summary: str = Field(min_length=1, max_length=SUMMARY_MAX_CHARS)


def build_vertex_model(model_id: str, project: str, location: str) -> GoogleModel:
    """Build a Gemini model served by Vertex AI (no network call at construction)."""
    return GoogleModel(model_id, provider=GoogleCloudProvider(project=project, location=location))


def build_sql_agent(model: Model) -> Agent[None, SqlDraft]:
    """Create the SQL agent; its validator re-runs C01-C03 and asks the model to retry."""
    agent = Agent[None, SqlDraft](
        model,
        output_type=SqlDraft,
        retries={"output": SQL_OUTPUT_RETRIES},
        model_settings=ModelSettings(temperature=SQL_TEMPERATURE, max_tokens=SQL_MAX_OUTPUT_TOKENS),
    )

    @agent.output_validator
    def _validate(ctx: RunContext[None], output: SqlDraft) -> SqlDraft:
        validation = validate_sql(output.sql)
        if not validation.is_valid:
            raise ModelRetry(f"{validation.reason}{RETRY_DETAIL_SEPARATOR}{RULE_EXPLANATION}")
        return output.model_copy(update={"sql": validation.sql})

    return agent


def build_summary_agent(model: Model) -> Agent[None, SummaryDraft]:
    """Create the summary agent."""
    return Agent[None, SummaryDraft](
        model,
        output_type=SummaryDraft,
        model_settings=ModelSettings(
            temperature=SUMMARY_TEMPERATURE, max_tokens=SUMMARY_MAX_OUTPUT_TOKENS
        ),
    )


def _rejection_detail(error: UnexpectedModelBehavior) -> str | None:
    """Return the validator reason when the failure is an exhausted SQL retry budget."""
    cause = error.__cause__
    if isinstance(cause, ModelRetry):
        return str(cause).split(RETRY_DETAIL_SEPARATOR, 1)[0]
    return None


class PydanticAiSqlGenerator:
    """SqlGenerator backed by a PydanticAI agent."""

    def __init__(self, model: Model) -> None:
        self._agent = build_sql_agent(model)

    async def generate(self, question: str, lang: Lang, period: Period | None) -> SqlDraft:
        try:
            result = await self._agent.run(
                build_sql_prompt(question, period), instructions=SQL_INSTRUCTIONS[lang]
            )
        except UnexpectedModelBehavior as error:
            detail = _rejection_detail(error)
            if detail is not None:
                raise SqlRejectedError(detail) from error
            raise LlmUnavailableError(str(error)) from error
        except _PROVIDER_ERRORS as error:
            raise LlmUnavailableError(str(error)) from error
        return result.output


class PydanticAiSummarizer:
    """Summarizer backed by a PydanticAI agent."""

    def __init__(self, model: Model) -> None:
        self._agent = build_summary_agent(model)

    async def summarize(self, question: str, lang: Lang, sql: str, rows: Sequence[Row]) -> str:
        try:
            result = await self._agent.run(
                build_summary_prompt(question, sql, rows),
                instructions=SUMMARY_INSTRUCTIONS[lang],
            )
        except _PROVIDER_ERRORS as error:
            raise LlmUnavailableError(str(error)) from error
        return result.output.summary
