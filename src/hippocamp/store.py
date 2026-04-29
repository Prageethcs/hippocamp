"""SQLite-backed storage for Hippocamp memories.

v0.0.1 stores embeddings as JSON arrays and ranks in Python. v0.1.0 will
swap in sqlite-vec for true vector search; the public `Store` API stays
the same.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from hippocamp.types import CompactReport, Inventory, RawRow

SCHEMA = """
CREATE TABLE IF NOT EXISTS memories (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    text TEXT NOT NULL,
    created_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    superseded_at TEXT,
    salience REAL NOT NULL DEFAULT 0,
    metadata TEXT NOT NULL DEFAULT '{}',
    embedding TEXT NOT NULL,
    extras TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_memories_kind ON memories(kind);
CREATE INDEX IF NOT EXISTS idx_memories_created_at ON memories(created_at);
"""


class Store:
    def __init__(self, path: str | Path) -> None:
        self._path = str(path)
        self._conn = sqlite3.connect(self._path, isolation_level=None)
        if self._path != ":memory:":
            self._conn.execute("PRAGMA journal_mode = WAL")
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.executescript(SCHEMA)

    def insert(
        self,
        *,
        id: str,
        kind: str,
        text: str,
        created_at: datetime,
        metadata: dict,
        embedding: list[float],
        extras: dict | None = None,
    ) -> None:
        self._conn.execute(
            """
            INSERT INTO memories (id, kind, text, created_at, last_seen_at,
                                  metadata, embedding, extras)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                id,
                kind,
                text,
                created_at.isoformat(),
                created_at.isoformat(),
                json.dumps(metadata),
                json.dumps(embedding),
                json.dumps(extras or {}),
            ),
        )

    def mark_superseded(self, ids: list[str], *, by: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        for old_id in ids:
            self._conn.execute(
                "UPDATE memories SET superseded_at = ? WHERE id = ?",
                (now, old_id),
            )

    def search(
        self,
        *,
        query_emb: list[float],
        kinds: list[str] | None,
        candidate_limit: int,
    ) -> list[RawRow]:
        sql = (
            "SELECT id, kind, text, created_at, last_seen_at, salience, "
            "metadata, embedding FROM memories WHERE superseded_at IS NULL"
        )
        params: list[Any] = []
        if kinds:
            placeholders = ",".join("?" * len(kinds))
            sql += f" AND kind IN ({placeholders})"
            params.extend(kinds)
        sql += " LIMIT ?"
        params.append(candidate_limit * 5)

        rows = self._conn.execute(sql, params).fetchall()
        return [
            RawRow(
                id=r[0],
                kind=r[1],
                text=r[2],
                created_at=datetime.fromisoformat(r[3]),
                last_seen_at=datetime.fromisoformat(r[4]),
                salience=r[5],
                metadata=json.loads(r[6]),
                embedding=json.loads(r[7]),
            )
            for r in rows
        ]

    def bump_salience(self, ids: list[str]) -> None:
        if not ids:
            return
        now = datetime.now(timezone.utc).isoformat()
        for mem_id in ids:
            self._conn.execute(
                "UPDATE memories SET salience = salience + 1.0, "
                "last_seen_at = ? WHERE id = ?",
                (now, mem_id),
            )

    def delete(self, id: str) -> None:
        self._conn.execute("DELETE FROM memories WHERE id = ?", (id,))

    def expire_before(self, cutoff: datetime) -> int:
        cur = self._conn.execute(
            "DELETE FROM memories WHERE created_at < ?",
            (cutoff.isoformat(),),
        )
        return cur.rowcount

    def compact(self) -> CompactReport:
        return CompactReport(merged=0, dropped=0)

    def inventory(self) -> Inventory:
        rows = self._conn.execute(
            "SELECT kind, COUNT(*) FROM memories WHERE superseded_at IS NULL "
            "GROUP BY kind"
        ).fetchall()
        counts = {r[0]: r[1] for r in rows}

        bytes_on_disk = 0
        if self._path != ":memory:":
            p = Path(self._path)
            if p.exists():
                bytes_on_disk = p.stat().st_size

        return Inventory(
            episodes=counts.get("episode", 0),
            facts=counts.get("fact", 0),
            preferences=counts.get("preference", 0),
            reflections=counts.get("reflection", 0),
            bytes_on_disk=bytes_on_disk,
            last_reflect=None,
        )

    def close(self) -> None:
        self._conn.close()
