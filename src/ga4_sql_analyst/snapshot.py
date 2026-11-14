"""Pre-recorded answers for the ready-made questions, served when a live dependency is down."""

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

from ga4_sql_analyst.models import AskRequest, AskResponse, Lang

DEFAULT_SNAPSHOT_PATH = Path(__file__).parent / "data" / "snapshot.json"
SCENARIO_MIN = 1
SCENARIO_MAX = 4
JSON_INDENT = 2


class SnapshotEntry(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    scenario: int = Field(ge=SCENARIO_MIN, le=SCENARIO_MAX)
    lang: Lang
    question: str
    response: AskResponse


_ENTRIES_ADAPTER = TypeAdapter(list[SnapshotEntry])


def _lookup_key(question: str, lang: Lang) -> tuple[str, Lang] | None:
    """Normalize like AskRequest does, then casefold; None when the question is invalid."""
    try:
        normalized = AskRequest(question=question, lang=lang).question
    except ValidationError:
        return None
    return normalized.casefold(), lang


class Snapshot:
    """Read-only index of snapshot entries by (normalized question, language)."""

    def __init__(self, entries: Sequence[SnapshotEntry]) -> None:
        self._entries = tuple(entries)
        self._index: dict[tuple[str, Lang], AskResponse] = {}
        for entry in self._entries:
            key = _lookup_key(entry.question, entry.lang)
            if key is not None:
                self._index[key] = entry.response

    @classmethod
    def load(cls, path: Path = DEFAULT_SNAPSHOT_PATH) -> Self:
        """Load and validate the snapshot JSON file."""
        entries = _ENTRIES_ADAPTER.validate_json(path.read_text(encoding="utf-8"))
        return cls(entries)

    @property
    def entries(self) -> tuple[SnapshotEntry, ...]:
        return self._entries

    def find(self, question: str, lang: Lang) -> AskResponse | None:
        """Return the recorded response for the question, or None."""
        key = _lookup_key(question, lang)
        return None if key is None else self._index.get(key)


def dump_entries(entries: Sequence[SnapshotEntry], path: Path) -> None:
    """Write entries as indented UTF-8 JSON (non-ASCII kept as is)."""
    data = _ENTRIES_ADAPTER.dump_python(list(entries), mode="json")
    path.write_text(json.dumps(data, indent=JSON_INDENT, ensure_ascii=False) + "\n", "utf-8")
