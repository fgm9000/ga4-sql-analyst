"""Tests for C04 (resolve_period) and period_bounds."""

from datetime import date

import pytest

import ga4_sql_analyst.domain as domain
from ga4_sql_analyst.domain import DATASET_END, DATASET_START, period_bounds, resolve_period
from ga4_sql_analyst.models import Period


@pytest.mark.parametrize(
    ("question", "start", "end"),
    [
        ("últimos 30 dias", date(2021, 1, 2), date(2021, 1, 31)),
        ("ultimos 7 dias", date(2021, 1, 25), date(2021, 1, 31)),
        ("last 7 days", date(2021, 1, 25), date(2021, 1, 31)),
        ("Últimos 1 dias", date(2021, 1, 31), date(2021, 1, 31)),
        ("hoje", date(2021, 1, 31), date(2021, 1, 31)),
        ("What happened today?", date(2021, 1, 31), date(2021, 1, 31)),
        ("ontem", date(2021, 1, 30), date(2021, 1, 30)),
        ("and yesterday?", date(2021, 1, 30), date(2021, 1, 30)),
        ("última semana", date(2021, 1, 25), date(2021, 1, 31)),
        ("ultima semana", date(2021, 1, 25), date(2021, 1, 31)),
        ("last week", date(2021, 1, 25), date(2021, 1, 31)),
        ("este mês", date(2021, 1, 1), date(2021, 1, 31)),
        ("this month", date(2021, 1, 1), date(2021, 1, 31)),
        ("último mês", date(2020, 12, 1), date(2020, 12, 31)),
        ("mês passado", date(2020, 12, 1), date(2020, 12, 31)),
        ("LAST MONTH", date(2020, 12, 1), date(2020, 12, 31)),
        ("último trimestre", date(2020, 11, 1), date(2020, 12, 31)),
        ("last quarter", date(2020, 11, 1), date(2020, 12, 31)),
        ("últimos 200 dias", date(2020, 11, 1), date(2021, 1, 31)),
        ("last 9999 days", date(2020, 11, 1), date(2021, 1, 31)),
    ],
)
def test_resolve_period(question: str, start: date, end: date) -> None:
    assert resolve_period(question) == Period(start=start, end=end, anchored=True)


@pytest.mark.parametrize(
    "question",
    ["Qual canal trouxe mais receita?", "últimos 0 dias", "last 0 days", "", "last 10000 days"],
)
def test_resolve_period_returns_none(question: str) -> None:
    assert resolve_period(question) is None


def test_first_expression_wins() -> None:
    first_yesterday = resolve_period("compare ontem com os últimos 7 dias")
    assert first_yesterday == Period(start=date(2021, 1, 30), end=date(2021, 1, 30), anchored=True)
    first_week = resolve_period("últimos 7 dias versus ontem")
    assert first_week == Period(start=date(2021, 1, 25), end=date(2021, 1, 31), anchored=True)


def test_period_never_leaves_dataset() -> None:
    for question in ("últimos 200 dias", "último trimestre", "hoje"):
        period = resolve_period(question)
        assert period is not None
        assert DATASET_START <= period.start <= period.end <= DATASET_END


def test_period_entirely_before_dataset_is_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(domain, "DATASET_START", date(2021, 1, 1))
    assert resolve_period("último trimestre") is None


def test_period_bounds_formats_yyyymmdd() -> None:
    period = Period(start=date(2021, 1, 2), end=date(2021, 1, 31), anchored=True)
    assert period_bounds(period) == ("20210102", "20210131")
