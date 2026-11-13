"""Testes dos contratos em models.py."""

from datetime import date

import pytest
from pydantic import ValidationError

from ga4_sql_analyst.models import (
    INTENT_MAX_CHARS,
    QUESTION_MAX_CHARS,
    QUESTION_MIN_CHARS,
    SQL_MAX_CHARS,
    AskRequest,
    AskResponse,
    CheckResult,
    Period,
    SqlDraft,
)


def test_question_is_normalized_to_nfc() -> None:
    decomposed = "café vendas"
    request = AskRequest(question=decomposed)
    assert request.question == "café vendas"


def test_question_whitespace_is_stripped_and_collapsed() -> None:
    request = AskRequest(question="  quanto \t vendeu\n\n  hoje  ")
    assert request.question == "quanto vendeu hoje"


def test_question_min_length_boundary() -> None:
    assert AskRequest(question="a" * QUESTION_MIN_CHARS).question == "aaa"
    with pytest.raises(ValidationError):
        AskRequest(question="a" * (QUESTION_MIN_CHARS - 1))


def test_question_min_length_is_checked_after_strip() -> None:
    with pytest.raises(ValidationError):
        AskRequest(question="   ab   ")


def test_question_max_length_boundary() -> None:
    assert len(AskRequest(question="a" * QUESTION_MAX_CHARS).question) == QUESTION_MAX_CHARS
    with pytest.raises(ValidationError):
        AskRequest(question="a" * (QUESTION_MAX_CHARS + 1))


def test_question_non_string_is_rejected() -> None:
    with pytest.raises(ValidationError):
        AskRequest.model_validate({"question": 123})


def test_lang_defaults_to_pt_and_rejects_unknown_values() -> None:
    assert AskRequest(question="abc").lang == "pt"
    assert AskRequest(question="abc", lang="en").lang == "en"
    with pytest.raises(ValidationError):
        AskRequest.model_validate({"question": "abc", "lang": "fr"})


def test_extra_fields_are_forbidden() -> None:
    with pytest.raises(ValidationError):
        AskRequest.model_validate({"question": "abc", "extra_field": 1})


def test_models_are_frozen() -> None:
    request = AskRequest(question="abc")
    with pytest.raises(ValidationError):
        request.question = "outra"


def test_period_accepts_same_day_and_rejects_reversed_range() -> None:
    same_day = Period(start=date(2021, 1, 31), end=date(2021, 1, 31), anchored=True)
    assert same_day.start == same_day.end
    with pytest.raises(ValidationError):
        Period(start=date(2021, 2, 1), end=date(2021, 1, 31), anchored=True)


def test_sql_draft_bounds() -> None:
    draft = SqlDraft(sql="x" * SQL_MAX_CHARS, tables=["events"], intent="i" * INTENT_MAX_CHARS)
    assert len(draft.sql) == SQL_MAX_CHARS
    with pytest.raises(ValidationError):
        SqlDraft(sql="", tables=[], intent="ok")
    with pytest.raises(ValidationError):
        SqlDraft(sql="x" * (SQL_MAX_CHARS + 1), tables=[], intent="ok")
    with pytest.raises(ValidationError):
        SqlDraft(sql="SELECT 1", tables=[], intent="i" * (INTENT_MAX_CHARS + 1))


def test_check_result_defaults_and_invalid_id() -> None:
    result = CheckResult(id="C03_limit", passed=True)
    assert result.authority == "code"
    assert result.detail is None
    assert result.bytes_estimated is None
    with pytest.raises(ValidationError):
        CheckResult.model_validate({"id": "C99_unknown", "passed": True})


def test_ask_response_defaults_are_independent_lists() -> None:
    first = AskResponse(status="blocked")
    second = AskResponse(status="unavailable")
    assert first.checks == []
    assert first.rows == []
    assert first.degraded is False
    assert first.checks is not second.checks
    assert first.rows is not second.rows


def test_ask_response_rows_accept_cell_values_only() -> None:
    response = AskResponse(
        status="answered",
        rows=[{"canal": "organic", "sessoes": 10, "taxa": 0.5, "ok": True, "extra": None}],
    )
    assert response.rows[0]["sessoes"] == 10
    with pytest.raises(ValidationError):
        AskResponse.model_validate({"status": "answered", "rows": [{"x": [1, 2]}]})


def test_status_rejects_unknown_value() -> None:
    with pytest.raises(ValidationError):
        AskResponse.model_validate({"status": "done"})
