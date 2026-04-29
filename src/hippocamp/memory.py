"""Hippocamp's public Memory class — the single entry point for the library.

Memory mutations (observe / assert_fact / assert_preference / forget) write
to two places: the append-only event log (`events.jsonl`) and the SQLite
cache (`store.db`). The event log is the source of truth; the cache is a
derived index that can be rebuilt by `replay()`.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Literal

from hippocamp.events import Event, EventLog, EventOp, new_event_id
from hippocamp.meta import StoreMeta, load_or_init_device_id, load_or_init_meta
from hippocamp.ranker import rank
from hippocamp.store import Store
from hippocamp.types import CompactReport, Inventory, RecallResult

Kind = Literal["episode", "fact", "preference", "reflection"]


class Memory:
    """Local-first agent memory.

    All data lives under a single directory containing `meta.json`,
    `events.jsonl`, and `store.db`. No network calls are made unless you
    opt in by passing an `llm` (used only by `reflect()`).

    Pass `path=":memory:"` to skip the event log entirely (used by tests
    and ephemeral integrations).
    """

    def __init__(
        self,
        path: str | Path = ":memory:",
        *,
        embedder: Callable[[str], list[float]] | None = None,
        llm: Any | None = None,
        device_id: str | None = None,
    ) -> None:
        self._path_str = str(path)
        self._store = Store(path)

        if embedder is None:
            from hippocamp.embedders import default_embedder

            embedder = default_embedder()
        self._embedder = embedder
        self._llm = llm

        self._meta: StoreMeta | None = None
        self._events: EventLog | None = None
        self._device_id: str

        if self._path_str == ":memory:":
            self._device_id = device_id or "in-memory"
        else:
            store_dir = Path(self._path_str).parent
            store_dir.mkdir(parents=True, exist_ok=True)
            embedder_name = getattr(embedder, "name", type(embedder).__name__)
            meta_path = store_dir / "meta.json"
            meta_was_new = not meta_path.exists()
            self._meta = load_or_init_meta(meta_path, embedder_name=embedder_name)
            self._device_id = device_id or load_or_init_device_id()
            self._events = EventLog(store_dir / "events", self._device_id)

            self._migrate_legacy_single_file_log()
            if meta_was_new and self._events.count() == 0:
                self._bootstrap_events_from_cache()

    @property
    def meta(self) -> StoreMeta | None:
        return self._meta

    @property
    def device_id(self) -> str:
        return self._device_id

    @property
    def events_dir(self) -> Path | None:
        return self._events.dir if self._events else None

    @property
    def events_own_file(self) -> Path | None:
        return self._events.own_file if self._events else None

    # ------------------------------------------------------------------ write

    def observe(
        self,
        text: str,
        *,
        actors: list[str] | None = None,
        at: datetime | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        eid = _new_id("ep")
        when = at or _now()
        self._emit(
            EventOp.OBSERVE,
            mem_id=eid,
            ts=when,
            text=text,
            actors=actors or [],
            metadata=metadata or {},
        )
        self._store.insert(
            id=eid,
            kind="episode",
            text=text,
            created_at=when,
            metadata=metadata or {},
            embedding=self._embedder(text),
            extras={"actors": actors or []},
        )
        return eid

    def assert_fact(
        self,
        text: str,
        *,
        evidence: list[str] | None = None,
        supersedes: list[str] | None = None,
    ) -> str:
        fid = _new_id("fa")
        when = _now()
        self._emit(
            EventOp.ASSERT_FACT,
            mem_id=fid,
            ts=when,
            text=text,
            evidence=evidence or [],
            supersedes=supersedes or [],
        )
        self._store.insert(
            id=fid,
            kind="fact",
            text=text,
            created_at=when,
            metadata={"evidence": evidence or [], "supersedes": supersedes or []},
            embedding=self._embedder(text),
        )
        if supersedes:
            self._store.mark_superseded(supersedes, by=fid, when=when)
        return fid

    def assert_preference(self, text: str, *, strength: float = 1.0) -> str:
        pid = _new_id("pr")
        when = _now()
        self._emit(
            EventOp.ASSERT_PREF,
            mem_id=pid,
            ts=when,
            text=text,
            strength=strength,
        )
        self._store.insert(
            id=pid,
            kind="preference",
            text=text,
            created_at=when,
            metadata={"strength": strength},
            embedding=self._embedder(text),
        )
        return pid

    # ------------------------------------------------------------------- read

    def recall(
        self,
        query: str | None = None,
        *,
        kinds: Iterable[Kind] | None = None,
        limit: int = 10,
        context: dict[str, Any] | None = None,
    ) -> list[RecallResult]:
        if query is None:
            return []

        query_emb = self._embedder(query)
        rows = self._store.search(
            query_emb=query_emb,
            kinds=list(kinds) if kinds else None,
            candidate_limit=max(limit * 4, 40),
        )

        ranked = rank(rows, query_emb=query_emb, context=context, now=_now())
        results = ranked[:limit]
        self._store.bump_salience([r.id for r in results])
        return results

    # ------------------------------------------------------------ consolidate

    def reflect(self, *, since: str | datetime | None = None):
        if self._llm is None:
            raise RuntimeError("reflect() requires an llm; pass `llm=...` to Memory()")
        from hippocamp.reflect import run_reflection

        return run_reflection(self._store, self._llm, since=since)

    # ----------------------------------------------------------------- forget

    def forget(self, id: str) -> None:
        when = _now()
        self._emit(EventOp.FORGET, mem_id=id, ts=when)
        self._store.tombstone(id, when=when)

    def expire_before(self, when: str | datetime) -> int:
        cutoff = _parse_when(when)
        ids = self._store.list_active_before(cutoff)
        for mem_id in ids:
            self.forget(mem_id)
        return len(ids)

    def compact(self) -> CompactReport:
        return self._store.compact()

    # ----------------------------------------------------------------- replay

    def replay(self) -> int:
        """Wipe the cache and rebuild it from `events.jsonl`. Returns event count.

        Idempotent. Used after embedder upgrades, after corrupting the cache,
        or after merging events from another device.
        """
        if self._events is None:
            raise RuntimeError("replay() requires an on-disk store")

        self._store.wipe()
        n = 0
        for event in self._events.read_all():
            self._apply(event)
            n += 1
        return n

    # ---------------------------------------------------------------- inspect

    def inspect(self) -> Inventory:
        return self._store.inventory()

    # --------------------------------------------------------------- lifecycle

    def close(self) -> None:
        self._store.close()

    # ---------------------------------------------------------------- internal

    def _emit(self, op: EventOp, *, mem_id: str, ts: datetime, **fields: Any) -> None:
        if self._events is None:
            return
        self._events.append(
            Event(
                id=new_event_id(),
                ts=ts,
                device=self._device_id,
                op=op,
                mem_id=mem_id,
                **fields,
            )
        )

    def _migrate_legacy_single_file_log(self) -> int:
        """Split a legacy `events.jsonl` (slice-1 layout) into per-device files.

        Slice 1.6 introduced per-device event files; an older single-file
        log is split by the `device` field on each event so writes from
        each origin device land in `events/<device>.jsonl`.
        """
        if self._events is None:
            return 0
        legacy = Path(self._path_str).parent / "events.jsonl"
        if not legacy.exists():
            return 0

        events_dir = self._events.dir
        events_dir.mkdir(parents=True, exist_ok=True)
        moved = 0
        with legacy.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                ev = Event.model_validate_json(line)
                target = events_dir / f"{ev.device}.jsonl"
                with target.open("a", encoding="utf-8") as out:
                    out.write(line + "\n")
                moved += 1
        legacy.unlink()
        return moved

    def _bootstrap_events_from_cache(self) -> int:
        """Generate events for rows already in the cache.

        Runs once when a pre-v0.3 store is opened for the first time
        under the new architecture. Without this, the cache and the
        (empty) event log would silently disagree, and `replay()`
        would lose every existing memory.

        Returns the number of events written.
        """
        import json as _json

        if self._events is None:
            return 0

        rows = self._store._conn.execute(
            "SELECT id, kind, text, created_at, superseded_at, metadata "
            "FROM memories ORDER BY created_at"
        ).fetchall()
        if not rows:
            return 0

        n = 0
        for mem_id, kind, text, created_at, superseded_at, metadata_json in rows:
            ts = datetime.fromisoformat(created_at)
            meta = _json.loads(metadata_json or "{}")

            if kind == "episode":
                self._events.append(
                    Event(
                        id=new_event_id(),
                        ts=ts,
                        device=self._device_id,
                        op=EventOp.OBSERVE,
                        mem_id=mem_id,
                        text=text or "",
                        metadata=meta,
                    )
                )
            elif kind == "fact":
                self._events.append(
                    Event(
                        id=new_event_id(),
                        ts=ts,
                        device=self._device_id,
                        op=EventOp.ASSERT_FACT,
                        mem_id=mem_id,
                        text=text or "",
                        evidence=meta.get("evidence", []) or [],
                        supersedes=meta.get("supersedes", []) or [],
                    )
                )
            elif kind == "preference":
                self._events.append(
                    Event(
                        id=new_event_id(),
                        ts=ts,
                        device=self._device_id,
                        op=EventOp.ASSERT_PREF,
                        mem_id=mem_id,
                        text=text or "",
                        strength=meta.get("strength", 1.0),
                    )
                )
            else:
                continue
            n += 1

            # If the row was already tombstoned, also emit a forget event
            # at the original tombstone time, so replay reconstructs the
            # superseded state correctly.
            if superseded_at:
                forget_ts = datetime.fromisoformat(superseded_at)
                self._events.append(
                    Event(
                        id=new_event_id(),
                        ts=forget_ts,
                        device=self._device_id,
                        op=EventOp.FORGET,
                        mem_id=mem_id,
                    )
                )
                n += 1

        return n

    def _apply(self, event: Event) -> None:
        """Apply an event to the cache only (no event emission). Used by replay."""
        if event.op == EventOp.OBSERVE:
            self._store.insert(
                id=event.mem_id,
                kind="episode",
                text=event.text or "",
                created_at=event.ts,
                metadata=event.metadata,
                embedding=self._embedder(event.text or ""),
                extras={"actors": event.actors},
            )
        elif event.op == EventOp.ASSERT_FACT:
            self._store.insert(
                id=event.mem_id,
                kind="fact",
                text=event.text or "",
                created_at=event.ts,
                metadata={
                    "evidence": event.evidence,
                    "supersedes": event.supersedes,
                },
                embedding=self._embedder(event.text or ""),
            )
            if event.supersedes:
                self._store.mark_superseded(
                    event.supersedes, by=event.mem_id, when=event.ts
                )
        elif event.op == EventOp.ASSERT_PREF:
            self._store.insert(
                id=event.mem_id,
                kind="preference",
                text=event.text or "",
                created_at=event.ts,
                metadata={"strength": event.strength or 1.0},
                embedding=self._embedder(event.text or ""),
            )
        elif event.op == EventOp.FORGET:
            self._store.tombstone(event.mem_id, when=event.ts)


# ---------------------------------------------------------------------- utils


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _parse_when(when: str | datetime) -> datetime:
    if isinstance(when, datetime):
        return when
    s = str(when).strip().lower()
    if s.endswith("d"):
        return _now() - timedelta(days=int(s[:-1]))
    if s.endswith("h"):
        return _now() - timedelta(hours=int(s[:-1]))
    return datetime.fromisoformat(s)
