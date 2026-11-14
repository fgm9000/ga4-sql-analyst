"""Testes de cache.py."""

import pytest

from ga4_sql_analyst.cache import CachingWarehouse, ResponseCache, normalize_question
from ga4_sql_analyst.errors import WarehouseUnavailableError
from ga4_sql_analyst.models import AskResponse
from ga4_sql_analyst.ports import Row


def _answer(summary: str = "ok") -> AskResponse:
    return AskResponse(status="answered", summary=summary)


def test_miss_returns_none() -> None:
    assert ResponseCache(max_entries=10).get("quanto vendeu", "pt") is None


def test_put_then_get_returns_same_response() -> None:
    cache = ResponseCache(max_entries=10)
    response = _answer()
    cache.put("quanto vendeu", "pt", response)
    assert cache.get("quanto vendeu", "pt") == response


def test_normalization_trims_collapses_spaces_and_casefolds() -> None:
    cache = ResponseCache(max_entries=10)
    cache.put("  Quanto   VENDEU \t hoje ", "pt", _answer())
    assert cache.get("quanto vendeu hoje", "pt") is not None


def test_normalization_applies_nfc() -> None:
    decomposed = "café vendas"
    composed = "café vendas"
    assert normalize_question(decomposed) == normalize_question(composed)
    cache = ResponseCache(max_entries=10)
    cache.put(decomposed, "pt", _answer())
    assert cache.get(composed, "pt") is not None


def test_language_is_part_of_the_key() -> None:
    cache = ResponseCache(max_entries=10)
    cache.put("how much", "en", _answer())
    assert cache.get("how much", "pt") is None


def test_blocked_response_is_cached() -> None:
    cache = ResponseCache(max_entries=10)
    blocked = AskResponse(status="blocked", reason="not_select")
    cache.put("delete everything", "en", blocked)
    assert cache.get("delete everything", "en") == blocked


def test_degraded_response_is_not_cached() -> None:
    cache = ResponseCache(max_entries=10)
    cache.put("quanto vendeu", "pt", AskResponse(status="answered", degraded=True))
    assert cache.get("quanto vendeu", "pt") is None


def test_unavailable_response_is_not_cached() -> None:
    cache = ResponseCache(max_entries=10)
    cache.put("quanto vendeu", "pt", AskResponse(status="unavailable"))
    assert cache.get("quanto vendeu", "pt") is None


def test_lru_evicts_least_recently_used_entry() -> None:
    cache = ResponseCache(max_entries=2)
    cache.put("alpha", "pt", _answer("a"))
    cache.put("beta", "pt", _answer("b"))
    assert cache.get("alpha", "pt") is not None  # alpha becomes most recent
    cache.put("gamma", "pt", _answer("c"))
    assert cache.get("beta", "pt") is None
    assert cache.get("alpha", "pt") is not None
    assert cache.get("gamma", "pt") is not None


class FakeWarehouse:
    """Warehouse double that counts calls and can be switched to failure mode."""

    def __init__(self) -> None:
        self.dry_run_calls = 0
        self.execute_calls = 0
        self.fail = False

    def dry_run(self, sql: str) -> int:
        self.dry_run_calls += 1
        if self.fail:
            raise WarehouseUnavailableError("down")
        return 123

    def execute(self, sql: str, max_bytes_billed: int) -> list[Row]:
        self.execute_calls += 1
        if self.fail:
            raise WarehouseUnavailableError("down")
        return [{"n": 1}]


def test_dry_run_calls_inner_once_for_same_sql() -> None:
    inner = FakeWarehouse()
    warehouse = CachingWarehouse(inner, max_entries=10)
    assert warehouse.dry_run("SELECT 1") == 123
    assert warehouse.dry_run("SELECT 1") == 123
    assert inner.dry_run_calls == 1


def test_execute_calls_inner_once_for_same_sql_and_cap() -> None:
    inner = FakeWarehouse()
    warehouse = CachingWarehouse(inner, max_entries=10)
    first = warehouse.execute("SELECT 1", 1_000)
    second = warehouse.execute("SELECT 1", 1_000)
    assert first == second == [{"n": 1}]
    assert inner.execute_calls == 1


def test_execute_different_cap_or_sql_is_a_miss() -> None:
    inner = FakeWarehouse()
    warehouse = CachingWarehouse(inner, max_entries=10)
    warehouse.execute("SELECT 1", 1_000)
    warehouse.execute("SELECT 1", 2_000)
    warehouse.execute("SELECT 2", 1_000)
    assert inner.execute_calls == 3


def test_empty_result_is_cached() -> None:
    class EmptyWarehouse(FakeWarehouse):
        def execute(self, sql: str, max_bytes_billed: int) -> list[Row]:
            self.execute_calls += 1
            return []

    inner = EmptyWarehouse()
    warehouse = CachingWarehouse(inner, max_entries=10)
    assert warehouse.execute("SELECT 1", 1_000) == []
    assert warehouse.execute("SELECT 1", 1_000) == []
    assert inner.execute_calls == 1


def test_warehouse_lru_evicts_oldest_dry_run() -> None:
    inner = FakeWarehouse()
    warehouse = CachingWarehouse(inner, max_entries=1)
    warehouse.dry_run("SELECT 1")
    warehouse.dry_run("SELECT 2")
    warehouse.dry_run("SELECT 1")
    assert inner.dry_run_calls == 3


def test_warehouse_lru_evicts_oldest_execution() -> None:
    inner = FakeWarehouse()
    warehouse = CachingWarehouse(inner, max_entries=1)
    warehouse.execute("SELECT 1", 1_000)
    warehouse.execute("SELECT 2", 1_000)
    warehouse.execute("SELECT 1", 1_000)
    assert inner.execute_calls == 3


def test_dry_run_errors_are_not_cached() -> None:
    inner = FakeWarehouse()
    warehouse = CachingWarehouse(inner, max_entries=10)
    inner.fail = True
    with pytest.raises(WarehouseUnavailableError):
        warehouse.dry_run("SELECT 1")
    inner.fail = False
    assert warehouse.dry_run("SELECT 1") == 123
    assert warehouse.dry_run("SELECT 1") == 123
    assert inner.dry_run_calls == 2


def test_execute_errors_are_not_cached() -> None:
    inner = FakeWarehouse()
    warehouse = CachingWarehouse(inner, max_entries=10)
    inner.fail = True
    with pytest.raises(WarehouseUnavailableError):
        warehouse.execute("SELECT 1", 1_000)
    inner.fail = False
    assert warehouse.execute("SELECT 1", 1_000) == [{"n": 1}]
    assert warehouse.execute("SELECT 1", 1_000) == [{"n": 1}]
    assert inner.execute_calls == 2
