"""Tests for the demo scenario constants."""

from ga4_sql_analyst.domain import period_bounds, resolve_period, validate_sql
from ga4_sql_analyst.scenarios import SCENARIOS


def test_four_numbered_scenarios_with_both_languages() -> None:
    assert [scenario.scenario for scenario in SCENARIOS] == [1, 2, 3, 4]
    for scenario in SCENARIOS:
        assert set(scenario.question) == {"pt", "en"}


def test_questions_are_unique() -> None:
    questions = [text for scenario in SCENARIOS for text in scenario.question.values()]
    assert len(questions) == len(set(questions))


def test_scenarios_one_to_three_pass_the_sql_guardrails() -> None:
    for scenario in SCENARIOS[:3]:
        assert validate_sql(scenario.offline_sql).is_valid


def test_scenario_four_is_blocked_by_the_ast() -> None:
    validation = validate_sql(SCENARIOS[3].offline_sql)
    assert not validation.is_valid
    assert validation.reason == "not_select"


def test_scenario_one_sql_uses_the_resolved_period() -> None:
    scenario = SCENARIOS[0]
    for question in scenario.question.values():
        period = resolve_period(question)
        assert period is not None
        start, end = period_bounds(period)
        assert f"BETWEEN '{start}' AND '{end}'" in scenario.offline_sql
