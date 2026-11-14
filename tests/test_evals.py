"""The offline evals are a CI gate: they must pass, and a broken guardrail must trip them."""

from evals import date_anchor_dataset, guardrail_dataset
from evals.run_offline import evaluate_gates


def _never_blocks(sql: str) -> bool:
    return False


def _always_blocks(sql: str) -> bool:
    return True


def _always_resolves(question: str) -> tuple[str, str] | None:
    return ("2021-01-01", "2021-01-31")


def test_datasets_have_minimum_size() -> None:
    assert len(guardrail_dataset.ADVERSARIAL) >= 22
    assert len(guardrail_dataset.LEGITIMATE) >= 8
    total = len(guardrail_dataset.ADVERSARIAL) + len(guardrail_dataset.LEGITIMATE)
    assert len(guardrail_dataset.build_dataset().cases) == total
    assert len(date_anchor_dataset.build_dataset().cases) >= 12


def test_offline_gates_pass() -> None:
    result = evaluate_gates()
    assert result.block_recall == 1.0
    assert result.false_block_rate == 0.0
    assert result.anchor_failures == 0
    assert result.passed


def test_gate_fails_when_guardrail_never_blocks() -> None:
    result = evaluate_gates(_never_blocks)
    assert result.block_recall == 0.0
    assert not result.passed


def test_gate_fails_when_guardrail_blocks_everything() -> None:
    result = evaluate_gates(_always_blocks)
    assert result.false_block_rate == 1.0
    assert not result.passed


def test_gate_fails_when_anchor_resolves_a_question_without_period() -> None:
    result = evaluate_gates(anchor_task=_always_resolves)
    assert result.anchor_failures > 0
    assert not result.passed
