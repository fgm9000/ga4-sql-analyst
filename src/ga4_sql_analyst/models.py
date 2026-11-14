"""API input and output contracts (immutable Pydantic v2 models)."""

import re
import unicodedata
from datetime import date
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Lang = Literal["pt", "en"]
Status = Literal["answered", "blocked", "unavailable"]
Authority = Literal["code", "llm"]
CheckId = Literal[
    "C01_select_only",
    "C02_allowed_tables",
    "C03_limit",
    "C04_date_anchor",
    "C05_cost_ceiling",
    "C06_summary_numbers",
]
CellValue = str | int | float | bool | None

QUESTION_MIN_CHARS = 3
QUESTION_MAX_CHARS = 500
SQL_MAX_CHARS = 4000
INTENT_MAX_CHARS = 200

_WHITESPACE_RUN = re.compile(r"\s+")


class AskRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    question: str = Field(min_length=QUESTION_MIN_CHARS, max_length=QUESTION_MAX_CHARS)
    lang: Lang = "pt"

    @field_validator("question", mode="before")
    @classmethod
    def _normalize_question(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        normalized = unicodedata.normalize("NFC", value.strip())
        return _WHITESPACE_RUN.sub(" ", normalized)


class SqlDraft(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    sql: str = Field(min_length=1, max_length=SQL_MAX_CHARS)
    tables: list[str]
    intent: str = Field(min_length=1, max_length=INTENT_MAX_CHARS)


class Period(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    start: date
    end: date
    anchored: bool

    @model_validator(mode="after")
    def _check_order(self) -> Self:
        if self.start > self.end:
            raise ValueError("start must be <= end")
        return self


class CheckResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: CheckId
    passed: bool
    authority: Authority = "code"
    detail: str | None = None
    bytes_estimated: int | None = None


class AskResponse(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    status: Status
    period: Period | None = None
    sql: str | None = None
    checks: list[CheckResult] = Field(default_factory=list)
    rows: list[dict[str, CellValue]] = Field(default_factory=list)
    summary: str | None = None
    degraded: bool = False
    reason: str | None = None


class ValidateRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    sql: str = Field(min_length=1, max_length=SQL_MAX_CHARS)


class ValidateResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    is_valid: bool
    sql: str
    checks: list[CheckResult]
    reason: str | None = None
