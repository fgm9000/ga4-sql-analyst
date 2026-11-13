"""Tests for C05 (check_cost) and C06 (ground_summary_numbers)."""

import pytest

from ga4_sql_analyst.domain import MIN_BILLED_BYTES, check_cost, ground_summary_numbers
from ga4_sql_analyst.models import CellValue

NO_CONTEXT: frozenset[float] = frozenset()
ROWS: list[dict[str, CellValue]] = [
    {"canal": "organic", "receita": 1234.56, "sessoes": 4000, "ratio": 0.1234, "flag": True},
    {"canal": "cpc", "receita": 800, "sessoes": 2500, "ratio": None, "flag": False},
]


def test_cost_zero_bytes_bills_minimum() -> None:
    result = check_cost(0, 400_000_000)
    assert result.id == "C05_cost_ceiling"
    assert result.passed is True
    assert result.authority == "code"
    assert result.bytes_estimated == 0
    assert result.detail == f"billed={MIN_BILLED_BYTES} max=400000000"


def test_cost_exactly_at_ceiling_passes() -> None:
    assert check_cost(400_000_000, 400_000_000).passed is True


def test_cost_one_byte_above_ceiling_fails() -> None:
    result = check_cost(400_000_001, 400_000_000)
    assert result.passed is False
    assert result.detail == "billed=400000001 max=400000000"


def test_cost_minimum_billing_can_exceed_tiny_ceiling() -> None:
    assert check_cost(1, MIN_BILLED_BYTES - 1).passed is False
    assert check_cost(1, MIN_BILLED_BYTES).passed is True


def test_cost_large_query_fails() -> None:
    result = check_cost(3_583_657_854, 400_000_000)
    assert result.passed is False
    assert result.bytes_estimated == 3_583_657_854


@pytest.mark.parametrize(("estimated", "ceiling"), [(-1, 100), (10, 0), (10, -5)])
def test_cost_invalid_arguments_raise(estimated: int, ceiling: int) -> None:
    with pytest.raises(ValueError, match="bytes_estimated"):
        check_cost(estimated, ceiling)


def test_summary_pt_fully_grounded() -> None:
    summary = "Organic gerou 1.234,56 em receita com 4.000 sessões; cpc teve 800."
    text, result = ground_summary_numbers(summary, ROWS, "pt", NO_CONTEXT)
    assert text == summary
    assert result.id == "C06_summary_numbers"
    assert result.passed is True
    assert result.detail is None


def test_summary_en_fully_grounded() -> None:
    summary = "Organic made 1,234.56 in revenue from 4,000 sessions; cpc had 800."
    text, result = ground_summary_numbers(summary, ROWS, "en", NO_CONTEXT)
    assert text == summary
    assert result.passed is True


def test_summary_invented_number_is_marked() -> None:
    text, result = ground_summary_numbers("Organic teve 9.999 sessões.", ROWS, "pt", NO_CONTEXT)
    assert text == "Organic teve [?] sessões."
    assert result.passed is False
    assert result.detail == "ungrounded:9.999"


def test_summary_multiple_invented_numbers_are_listed() -> None:
    text, result = ground_summary_numbers("Got 77 and 4,000 and 55.5.", ROWS, "en", NO_CONTEXT)
    assert text == "Got [?] and 4,000 and [?]."
    assert result.detail == "ungrounded:77,55.5"


def test_summary_percent_from_ratio_is_grounded() -> None:
    text, result = ground_summary_numbers("A taxa foi de 12,3%.", ROWS, "pt", NO_CONTEXT)
    assert text == "A taxa foi de 12,3%."
    assert result.passed is True
    text_en, result_en = ground_summary_numbers("Rate was 12.3%.", ROWS, "en", NO_CONTEXT)
    assert text_en == "Rate was 12.3%."
    assert result_en.passed is True


def test_summary_invented_percent_keeps_percent_sign() -> None:
    text, result = ground_summary_numbers("Cresceu 45,5%.", ROWS, "pt", NO_CONTEXT)
    assert text == "Cresceu [?]%."
    assert result.detail == "ungrounded:45,5"


def test_summary_context_numbers_are_not_marked() -> None:
    summary = "Nos últimos 30 dias de 2021 a receita foi 800."
    text, result = ground_summary_numbers(summary, ROWS, "pt", frozenset({30.0, 2021.0}))
    assert text == summary
    assert result.passed is True


def test_summary_year_without_context_is_marked() -> None:
    text, result = ground_summary_numbers("Em 2021 foram 800.", ROWS, "pt", NO_CONTEXT)
    assert text == "Em [?] foram 800."
    assert result.detail == "ungrounded:2021"


def test_summary_bool_cells_are_ignored() -> None:
    rows: list[dict[str, CellValue]] = [{"flag": True, "other": False}]
    text, result = ground_summary_numbers("Valor 1 e 0.", rows, "pt", NO_CONTEXT)
    assert text == "Valor [?] e [?]."
    assert result.passed is False


def test_summary_rounding_to_written_decimals_is_grounded() -> None:
    rows: list[dict[str, CellValue]] = [{"v": 3.14159}]
    text, result = ground_summary_numbers("Pi ficou em 3,14.", rows, "pt", NO_CONTEXT)
    assert text == "Pi ficou em 3,14."
    assert result.passed is True
    text_off, _ = ground_summary_numbers("Pi ficou em 3,30.", rows, "pt", NO_CONTEXT)
    assert text_off == "Pi ficou em [?]."


def test_summary_relative_tolerance() -> None:
    rows: list[dict[str, CellValue]] = [{"v": 1000}]
    assert ground_summary_numbers("Total 1004", rows, "pt", NO_CONTEXT)[1].passed is True
    assert ground_summary_numbers("Total 1006", rows, "pt", NO_CONTEXT)[1].passed is False


def test_summary_negative_numbers() -> None:
    rows: list[dict[str, CellValue]] = [{"delta": -12.5}]
    text, result = ground_summary_numbers("Variação de -12,5 no período.", rows, "pt", NO_CONTEXT)
    assert text == "Variação de -12,5 no período."
    assert result.passed is True


def test_summary_digits_inside_words_are_ignored() -> None:
    rows: list[dict[str, CellValue]] = [{"v": 5}]
    text, result = ground_summary_numbers("Q4 e 5.", rows, "en", NO_CONTEXT)
    assert text == "Q4 e 5."
    assert result.passed is True


def test_summary_without_numbers() -> None:
    text, result = ground_summary_numbers("Nada a relatar.", [], "pt", NO_CONTEXT)
    assert text == "Nada a relatar."
    assert result.passed is True
    assert result.detail is None
