"""Offline eval gate (no LLM, no network, no BigQuery): exits 1 when a guardrail regresses."""

import sys
from collections.abc import Callable
from dataclasses import dataclass

from pydantic_evals.reporting import EvaluationReport
from pydantic_evals.reporting.analyses import ScalarResult

from evals import date_anchor_dataset, guardrail_dataset


@dataclass(frozen=True)
class GateResult:
    block_recall: float
    false_block_rate: float
    anchor_failures: int

    @property
    def passed(self) -> bool:
        return (
            self.block_recall >= 1.0 and self.false_block_rate <= 0.0 and self.anchor_failures == 0
        )


def _scalar(report: EvaluationReport[str, bool, None], title: str) -> float:
    for analysis in report.analyses:
        if isinstance(analysis, ScalarResult) and analysis.title == title:
            return float(analysis.value)
    raise LookupError(f"missing scalar analysis: {title}")


def evaluate_gates(
    guardrail_task: Callable[[str], bool] = guardrail_dataset.guardrail_task,
    anchor_task: Callable[
        [str], date_anchor_dataset.Bounds | None
    ] = date_anchor_dataset.anchor_task,
    *,
    show_reports: bool = False,
) -> GateResult:
    guardrails = guardrail_dataset.build_dataset().evaluate_sync(
        guardrail_task, progress=False, max_concurrency=1
    )
    anchors = date_anchor_dataset.build_dataset().evaluate_sync(
        anchor_task, progress=False, max_concurrency=1
    )
    if show_reports:
        guardrails.print(include_input=False, include_output=True, include_expected_output=True)
        anchors.print(include_input=True, include_output=True, include_expected_output=True)
    # EqualsExpected skips cases whose expected output is None, so compare outputs directly.
    anchor_failures = len(anchors.failures) + sum(
        1 for case in anchors.cases if case.output != case.expected_output
    )
    broken = bool(guardrails.failures)
    return GateResult(
        block_recall=0.0 if broken else _scalar(guardrails, guardrail_dataset.RECALL_TITLE),
        false_block_rate=1.0
        if broken
        else _scalar(guardrails, guardrail_dataset.FALSE_BLOCK_TITLE),
        anchor_failures=anchor_failures,
    )


def main() -> None:
    result = evaluate_gates(show_reports=True)
    sys.stdout.write(
        f"block_recall={result.block_recall:.3f} false_block_rate={result.false_block_rate:.3f} "
        f"anchor_failures={result.anchor_failures}\n"
    )
    if not result.passed:
        sys.stdout.write("GATE FAILED\n")
        sys.exit(1)
    sys.stdout.write("GATE PASSED\n")


if __name__ == "__main__":
    main()
