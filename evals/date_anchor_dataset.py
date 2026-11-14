"""Offline eval: relative period expressions must resolve against the dataset anchor (C04)."""

from pydantic_evals import Case, Dataset
from pydantic_evals.evaluators import EqualsExpected

from ga4_sql_analyst.domain import resolve_period

Bounds = tuple[str, str]

CASES: dict[str, tuple[str, Bounds | None]] = {
    "today_pt": ("hoje", ("2021-01-31", "2021-01-31")),
    "today_en": ("What happened today?", ("2021-01-31", "2021-01-31")),
    "yesterday_pt": ("ontem", ("2021-01-30", "2021-01-30")),
    "yesterday_en": ("and yesterday?", ("2021-01-30", "2021-01-30")),
    "last_30_days_pt": ("últimos 30 dias", ("2021-01-02", "2021-01-31")),
    "last_7_days_en": ("last 7 days", ("2021-01-25", "2021-01-31")),
    "last_week_pt": ("última semana", ("2021-01-25", "2021-01-31")),
    "last_week_en": ("last week", ("2021-01-25", "2021-01-31")),
    "this_month_pt": ("este mês", ("2021-01-01", "2021-01-31")),
    "this_month_en": ("this month", ("2021-01-01", "2021-01-31")),
    "last_month_pt": ("último mês", ("2020-12-01", "2020-12-31")),
    "past_month_pt": ("mês passado", ("2020-12-01", "2020-12-31")),
    "last_quarter_pt": ("último trimestre", ("2020-11-01", "2020-12-31")),
    "last_quarter_en": ("last quarter", ("2020-11-01", "2020-12-31")),
    "clamped_to_dataset": ("últimos 200 dias", ("2020-11-01", "2021-01-31")),
    "no_period": ("Qual canal trouxe mais receita?", None),
    "zero_days_pt": ("últimos 0 dias", None),
    "zero_days_en": ("last 0 days", None),
}


def anchor_task(question: str) -> Bounds | None:
    """Resolve the question to ISO (start, end), or None when it has no period."""
    period = resolve_period(question)
    if period is None:
        return None
    return period.start.isoformat(), period.end.isoformat()


def build_dataset() -> Dataset[str, Bounds | None, None]:
    return Dataset[str, Bounds | None, None](
        name="date_anchor",
        cases=[
            Case(name=name, inputs=question, expected_output=expected)
            for name, (question, expected) in CASES.items()
        ],
        evaluators=[EqualsExpected()],
    )
