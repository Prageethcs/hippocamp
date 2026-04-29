"""Append-only event log — the source of truth for Hippocamp memory.

Every public mutation on `Memory` (observe / assert_fact / assert_preference /
forget) writes one event to `events.jsonl`. The SQLite cache is derived; if
you delete it and call `Memory.replay()`, you get the same state back.

Events carry text only. Embeddings are derived locally from text by each
device's embedder, and are never written to the event log.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Iterator

from pydantic import BaseModel, Field


class EventOp(str, Enum):
    OBSERVE = "observe"
    ASSERT_FACT = "assert_fact"
    ASSERT_PREF = "assert_pref"
    FORGET = "forget"


class Event(BaseModel):
    """A single mutation, recorded immutably in `events.jsonl`."""

    id: str
    ts: datetime
    device: str
    op: EventOp
    mem_id: str
    text: str | None = None
    actors: list[str] = Field(default_factory=list)
    metadata: dict = Field(default_factory=dict)
    evidence: list[str] = Field(default_factory=list)
    strength: float | None = None
    supersedes: list[str] = Field(default_factory=list)


def new_event_id() -> str:
    return f"ev_{uuid.uuid4().hex[:16]}"


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


class EventLog:
    """Append-only writer/reader for `events.jsonl`."""

    def __init__(self, path: Path) -> None:
        self._path = Path(path)

    @property
    def path(self) -> Path:
        return self._path

    def append(self, event: Event) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as f:
            f.write(event.model_dump_json() + "\n")

    def read_all(self) -> Iterator[Event]:
        if not self._path.exists():
            return
        with self._path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                yield Event.model_validate_json(line)

    def count(self) -> int:
        if not self._path.exists():
            return 0
        with self._path.open(encoding="utf-8") as f:
            return sum(1 for line in f if line.strip())
