"""Per-device append-only event logs — the source of truth for Hippocamp.

Each device writes only to its own file: `events/<device_id>.jsonl`. Reads
merge events from every `*.jsonl` file in `events/`, sorted by timestamp.

This eliminates concurrent-write conflicts on cloud-synced storage
(Dropbox, iCloud, Syncthing, etc.) because no file ever has more than one
writer. Pulling another device's events file in via any sync mechanism is
a no-op for everyone else's writes.

Events carry text only. Embeddings are derived locally by each device's
embedder and never written to the log.
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
    """A single mutation, recorded immutably in this device's event file."""

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
    """Per-device writer + multi-file reader for events.

    `append()` writes only to this device's file (`<device_id>.jsonl`).
    `read_all()` reads every `*.jsonl` in the events dir, ordered by ts.
    """

    def __init__(self, events_dir: Path, device_id: str) -> None:
        self._dir = Path(events_dir)
        self._device_id = device_id
        self._own_file = self._dir / f"{device_id}.jsonl"

    @property
    def dir(self) -> Path:
        return self._dir

    @property
    def own_file(self) -> Path:
        return self._own_file

    @property
    def device_id(self) -> str:
        return self._device_id

    def append(self, event: Event) -> None:
        """Append to *this* device's file only."""
        self._dir.mkdir(parents=True, exist_ok=True)
        with self._own_file.open("a", encoding="utf-8") as f:
            f.write(event.model_dump_json() + "\n")

    def device_files(self) -> list[Path]:
        if not self._dir.exists():
            return []
        return sorted(self._dir.glob("*.jsonl"))

    def read_all(self) -> Iterator[Event]:
        """Yield every event across every device file, ordered by (ts, id).

        Sorting by timestamp gives a deterministic global order. Slight
        clock skew between devices is tolerated — for our access patterns
        (idempotent inserts, supersede-by-id, tombstones), small reorders
        don't change the eventual state.
        """
        events: list[Event] = []
        for path in self.device_files():
            with path.open(encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    events.append(Event.model_validate_json(line))
        events.sort(key=lambda e: (e.ts, e.id))
        for e in events:
            yield e

    def count(self) -> int:
        n = 0
        for path in self.device_files():
            with path.open(encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        n += 1
        return n

    def count_own(self) -> int:
        if not self._own_file.exists():
            return 0
        with self._own_file.open(encoding="utf-8") as f:
            return sum(1 for line in f if line.strip())
