"""In-memory LRU caches for answers and warehouse calls.

Both caches are safe without a TTL because the dataset is frozen (ADR 002, camada 2):
the same question and the same SQL always produce the same result. Entries are evicted
only by the LRU policy, never by age.
"""

import re
import unicodedata
from collections import OrderedDict
from collections.abc import Hashable

from ga4_sql_analyst.models import AskResponse, Lang, Status
from ga4_sql_analyst.ports import Row, Warehouse

DEFAULT_MAX_ENTRIES = 500
CACHEABLE_STATUSES: frozenset[Status] = frozenset({"answered", "blocked"})
_WHITESPACE_RUN = re.compile(r"\s+")


def normalize_question(question: str) -> str:
    """Normalize a question for cache keys: NFC, trimmed, single spaces, casefolded."""
    normalized = unicodedata.normalize("NFC", question).strip()
    return _WHITESPACE_RUN.sub(" ", normalized).casefold()


class _LruStore[K: Hashable, V]:
    """Bounded mapping that evicts the least recently used entry first."""

    def __init__(self, max_entries: int) -> None:
        self._max_entries = max_entries
        self._items: OrderedDict[K, V] = OrderedDict()

    def get(self, key: K) -> V | None:
        """Return the stored value and mark it as most recently used."""
        value = self._items.get(key)
        if value is not None:
            self._items.move_to_end(key)
        return value

    def put(self, key: K, value: V) -> None:
        """Store a value, evicting the least recently used entries above the limit."""
        self._items[key] = value
        self._items.move_to_end(key)
        while len(self._items) > self._max_entries:
            self._items.popitem(last=False)


class ResponseCache:
    """Caches complete answers keyed by normalized question and language."""

    def __init__(self, max_entries: int = DEFAULT_MAX_ENTRIES) -> None:
        self._store: _LruStore[tuple[str, Lang], AskResponse] = _LruStore(max_entries)

    def get(self, question: str, lang: Lang) -> AskResponse | None:
        """Return the cached answer for this question and language, if any."""
        return self._store.get((normalize_question(question), lang))

    def put(self, question: str, lang: Lang, response: AskResponse) -> None:
        """Store only complete, non-degraded answers; degraded or unavailable ones are skipped."""
        if response.degraded or response.status not in CACHEABLE_STATUSES:
            return
        self._store.put((normalize_question(question), lang), response)


class CachingWarehouse:
    """Warehouse decorator that caches dry runs and executions. Errors are never cached.

    Cached row lists are shared with callers, so they must not be mutated.
    """

    def __init__(self, inner: Warehouse, max_entries: int = DEFAULT_MAX_ENTRIES) -> None:
        self._inner = inner
        self._dry_runs: _LruStore[str, int] = _LruStore(max_entries)
        self._executions: _LruStore[tuple[str, int], list[Row]] = _LruStore(max_entries)

    def dry_run(self, sql: str) -> int:
        """Return the cached byte estimate for this SQL, or ask the inner warehouse once."""
        cached = self._dry_runs.get(sql)
        if cached is not None:
            return cached
        estimate = self._inner.dry_run(sql)
        self._dry_runs.put(sql, estimate)
        return estimate

    def execute(self, sql: str, max_bytes_billed: int) -> list[Row]:
        """Return cached rows for this SQL and byte cap, or execute once."""
        key = (sql, max_bytes_billed)
        cached = self._executions.get(key)
        if cached is not None:
            return cached
        rows = self._inner.execute(sql, max_bytes_billed)
        self._executions.put(key, rows)
        return rows
