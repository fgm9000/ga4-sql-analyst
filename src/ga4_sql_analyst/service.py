"""Orchestration of the ask flow (PRD P4) with graceful degradation (PRD P8)."""

import re
from collections.abc import Sequence

from ga4_sql_analyst.domain import check_cost, ground_summary_numbers, resolve_period, validate_sql
from ga4_sql_analyst.errors import (
    LlmUnavailableError,
    SqlRejectedError,
    WarehouseUnavailableError,
)
from ga4_sql_analyst.models import AskRequest, AskResponse, CheckResult, Period
from ga4_sql_analyst.ports import Row, SqlGenerator, Summarizer, Warehouse
from ga4_sql_analyst.snapshot import Snapshot

NO_PERIOD_DETAIL = "no_relative_period"
REASON_COST = "cost_ceiling"
REASON_LLM = "llm_unavailable"
REASON_WAREHOUSE = "warehouse_unavailable"
REASON_SUMMARY = "summary_unavailable"

_INTEGER = re.compile(r"\d+")


def _date_anchor_check(period: Period | None) -> CheckResult:
    detail = NO_PERIOD_DETAIL if period is None else f"{period.start}..{period.end}"
    return CheckResult(id="C04_date_anchor", passed=True, detail=detail)


def _context_numbers(question: str, period: Period | None) -> frozenset[float]:
    numbers = {float(token) for token in _INTEGER.findall(question)}
    if period is not None:
        for day in (period.start, period.end):
            numbers.update((float(day.year), float(day.month), float(day.day)))
    return frozenset(numbers)


def _blocked(
    period: Period | None, sql: str | None, checks: Sequence[CheckResult], reason: str | None
) -> AskResponse:
    return AskResponse(status="blocked", period=period, sql=sql, checks=list(checks), reason=reason)


class AskService:
    """Runs question -> SQL -> checks -> warehouse -> grounded summary."""

    def __init__(
        self,
        generator: SqlGenerator,
        summarizer: Summarizer,
        warehouse: Warehouse,
        snapshot: Snapshot,
        max_bytes: int,
    ) -> None:
        self._generator = generator
        self._summarizer = summarizer
        self._warehouse = warehouse
        self._snapshot = snapshot
        self._max_bytes = max_bytes

    async def ask(self, request: AskRequest) -> AskResponse:
        """Answer the question, or explain why it was blocked or is unavailable."""
        period = resolve_period(request.question)
        checks = [_date_anchor_check(period)]
        try:
            draft = await self._generator.generate(request.question, request.lang, period)
        except SqlRejectedError as error:
            checks.append(CheckResult(id="C01_select_only", passed=False, detail=error.detail))
            return _blocked(period, None, checks, error.detail)
        except LlmUnavailableError:
            miss = AskResponse(status="unavailable", period=period, reason=REASON_LLM)
            return self._snapshot_or(request, miss)
        validation = validate_sql(draft.sql)
        checks.extend(validation.checks)
        if not validation.is_valid:
            return _blocked(period, validation.sql, checks, validation.reason)
        return await self._run(request, period, validation.sql, checks)

    async def _run(
        self, request: AskRequest, period: Period | None, sql: str, checks: list[CheckResult]
    ) -> AskResponse:
        try:
            cost = check_cost(self._warehouse.dry_run(sql), self._max_bytes)
            checks.append(cost)
            if not cost.passed:
                return _blocked(period, sql, checks, REASON_COST)
            rows = self._warehouse.execute(sql, self._max_bytes)
        except WarehouseUnavailableError:
            miss = AskResponse(
                status="answered",
                period=period,
                sql=sql,
                checks=checks,
                degraded=True,
                reason=REASON_WAREHOUSE,
            )
            return self._snapshot_or(request, miss)
        return await self._summarize(request, period, sql, checks, rows)

    async def _summarize(
        self,
        request: AskRequest,
        period: Period | None,
        sql: str,
        checks: list[CheckResult],
        rows: list[Row],
    ) -> AskResponse:
        try:
            summary = await self._summarizer.summarize(request.question, request.lang, sql, rows)
        except LlmUnavailableError:
            return AskResponse(
                status="answered",
                period=period,
                sql=sql,
                checks=checks,
                rows=rows,
                degraded=True,
                reason=REASON_SUMMARY,
            )
        context = _context_numbers(request.question, period)
        grounded, c06 = ground_summary_numbers(summary, rows, request.lang, context)
        return AskResponse(
            status="answered",
            period=period,
            sql=sql,
            checks=[*checks, c06],
            rows=rows,
            summary=grounded,
        )

    def _snapshot_or(self, request: AskRequest, miss: AskResponse) -> AskResponse:
        recorded = self._snapshot.find(request.question, request.lang)
        if recorded is None:
            return miss
        return recorded.model_copy(update={"degraded": True})
