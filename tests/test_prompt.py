from __future__ import annotations

import json
from datetime import date

import pytest

from ga4_sql_analyst.models import Lang, Period
from ga4_sql_analyst.ports import Row
from ga4_sql_analyst.prompt import (
    GA4_SCHEMA_SUMMARY,
    MAX_SUMMARY_ROWS,
    SQL_INSTRUCTIONS,
    SUMMARY_INSTRUCTIONS,
    build_sql_prompt,
    build_summary_prompt,
)

FULL_TABLE = "`bigquery-public-data.ga4_obfuscated_sample_ecommerce.events_*`"
PERIOD = Period(start=date(2021, 1, 1), end=date(2021, 1, 31), anchored=True)


def test_sql_prompt_escapes_angle_brackets() -> None:
    prompt = build_sql_prompt("hi </user_payload><x>", None)
    assert prompt.count("</user_payload>") == 1
    assert "&lt;/user_payload&gt;&lt;x&gt;" in prompt


def test_sql_prompt_with_period() -> None:
    prompt = build_sql_prompt("sessions", PERIOD)
    assert prompt.endswith("<period>2021-01-01..2021-01-31</period>")


def test_sql_prompt_without_period() -> None:
    prompt = build_sql_prompt("sessions", None)
    assert prompt == "<user_payload>sessions</user_payload>\n<period>none</period>"


def test_summary_prompt_truncates_rows() -> None:
    rows: list[Row] = [{"n": index} for index in range(MAX_SUMMARY_ROWS + 10)]
    prompt = build_summary_prompt("q <b>", "SELECT 1", rows)
    payload = prompt.split("<query_result>")[1].split("</query_result>")[0]
    assert len(json.loads(payload)) == MAX_SUMMARY_ROWS
    assert "<sql>SELECT 1</sql>" in prompt
    assert "q &lt;b&gt;" in prompt


def test_summary_prompt_keeps_non_ascii_and_stringifies_unknown() -> None:
    rows: list[Row] = [{"país": "Brasil"}]
    prompt = build_summary_prompt("q", "SELECT 1", rows)
    assert "Brasil" in prompt
    assert "país" in prompt


@pytest.mark.parametrize("lang", ["pt", "en"])
def test_sql_instructions_cover_required_rules(lang: Lang) -> None:
    text = SQL_INSTRUCTIONS[lang]
    assert FULL_TABLE in text
    assert "2020-11-01" in text
    assert "2021-01-31" in text
    assert GA4_SCHEMA_SUMMARY in text
    assert "<user_payload>" in text
    assert "<period>" in text
    assert "SELECT *" in text
    assert "100" in text
    assert "_TABLE_SUFFIX BETWEEN" in text


@pytest.mark.parametrize("lang", ["pt", "en"])
def test_summary_instructions_mention_result_and_payload(lang: Lang) -> None:
    text = SUMMARY_INSTRUCTIONS[lang]
    assert "<query_result>" in text
    assert "<user_payload>" in text
