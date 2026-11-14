"""Tests for the snapshot loader and lookup."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from ga4_sql_analyst.domain import validate_sql
from ga4_sql_analyst.models import AskResponse
from ga4_sql_analyst.scenarios import SCENARIOS
from ga4_sql_analyst.snapshot import (
    DEFAULT_SNAPSHOT_PATH,
    Snapshot,
    SnapshotEntry,
    dump_entries,
)

QUESTION = "Qual canal trouxe mais receita nos últimos 30 dias?"


def _entry(question: str = QUESTION, scenario: int = 1) -> SnapshotEntry:
    response = AskResponse(status="answered", summary="cached")
    return SnapshotEntry(scenario=scenario, lang="pt", question=question, response=response)


def test_packaged_snapshot_covers_every_scenario_and_language() -> None:
    snapshot = Snapshot.load()
    assert len(snapshot.entries) == len(SCENARIOS) * 2
    for scenario in SCENARIOS:
        for lang, question in scenario.question.items():
            assert snapshot.find(question, lang) is not None


def test_packaged_snapshot_statuses_match_the_scenarios() -> None:
    snapshot = Snapshot.load(DEFAULT_SNAPSHOT_PATH)
    for entry in snapshot.entries:
        response = entry.response
        assert response.degraded is False
        if entry.scenario <= 2:
            assert response.status == "answered"
        elif entry.scenario == 3:
            assert response.status == "blocked"
            assert response.reason == "cost_ceiling"
        else:
            # Live: the LLM ignores the injection and writes a harmless SELECT (layer 1).
            # Offline: the fake model returns DELETE and the AST blocks it (layer 2).
            assert response.status in {"answered", "blocked"}
            if response.status == "answered":
                assert response.sql is not None
                assert validate_sql(response.sql).is_valid
        # No ungrounded-number marker may ship in the demo snapshot.
        assert all(check.passed for check in response.checks if check.id == "C06_summary_numbers")


def test_find_normalizes_whitespace_and_case() -> None:
    snapshot = Snapshot([_entry()])
    messy = "  QUAL canal   trouxe mais receita\nnos últimos 30 dias?  "
    found = snapshot.find(messy, "pt")
    assert found is not None
    assert found.summary == "cached"


def test_find_misses_other_language_and_unknown_question() -> None:
    snapshot = Snapshot([_entry()])
    assert snapshot.find(QUESTION, "en") is None
    assert snapshot.find("Outra pergunta qualquer", "pt") is None


def test_find_returns_none_for_invalid_question() -> None:
    assert Snapshot([_entry()]).find("ab", "pt") is None


def test_entries_with_invalid_questions_are_not_indexed() -> None:
    snapshot = Snapshot([_entry(question="x")])
    assert len(snapshot.entries) == 1
    assert snapshot.find("x", "pt") is None


def test_dump_then_load_round_trips(tmp_path: Path) -> None:
    target = tmp_path / "snapshot.json"
    dump_entries([_entry()], target)
    text = target.read_text(encoding="utf-8")
    assert "últimos" in text
    assert text.endswith("\n")
    loaded = Snapshot.load(target)
    assert loaded.entries == (_entry(),)


def test_scenario_out_of_range_is_rejected() -> None:
    with pytest.raises(ValidationError):
        _entry(scenario=5)


def test_load_rejects_malformed_file(tmp_path: Path) -> None:
    target = tmp_path / "bad.json"
    target.write_text('[{"scenario": 1}]', encoding="utf-8")
    with pytest.raises(ValidationError):
        Snapshot.load(target)
