"""Hippocamp's public Memory class — the single entry point for the library."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Literal

from hippocamp.ranker import rank
from hippocamp.store import Store
from hippocamp.types import CompactReport, Inventory, RecallResult

Kind = Literal["episode", "fact", "preference", "reflection"]


class Memory:
    """Local-first agent memory.

    All data lives in a single SQLite file. No network calls are made unless
    you opt in by passing an `llm` (used only by `reflect()`).
    """

    def __init__(
        self,
        path: str | Path = ":memory:",
        *,
        embedder: Callable[[str], list[float]] | None = None,
        llm: Any | None = None,
    ) -> None:
        self._store = Store(path)
        if embedder is None:
            from hippocamp.embedders import default_embedder

            embedder = default_embedder()
        self._embedder = embedder
        self._llm = llm

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
        self._store.insert(
            id=eid,
            kind="episode",
            text=text,
            created_at=at or _now(),
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
        self._store.insert(
            id=fid,
            kind="fact",
            text=text,
            created_at=_now(),
            metadata={"evidence": evidence or [], "supersedes": supersedes or []},
            embedding=self._embedder(text),
        )
        if supersedes:
            self._store.mark_superseded(supersedes, by=fid)
        return fid

    def assert_preference(self, text: str, *, strength: float = 1.0) -> str:
        pid = _new_id("pr")
        self._store.insert(
            id=pid,
            kind="preference",
            text=text,
            created_at=_now(),
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
        self._store.delete(id)

    def expire_before(self, when: str | datetime) -> int:
        return self._store.expire_before(_parse_when(when))

    def compact(self) -> CompactReport:
        return self._store.compact()

    # ---------------------------------------------------------------- inspect

    def inspect(self) -> Inventory:
        return self._store.inventory()

    # --------------------------------------------------------------- lifecycle

    def close(self) -> None:
        self._store.close()


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
