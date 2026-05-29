"""SQLite-backed storage for Hippocamp memories.

Persistence: every memory row lives in the ``memories`` table with its
embedding stored as a JSON array (for portability / human inspection /
event-log replay) AND, when sqlite-vec is available, mirrored into a
``memories_vec`` virtual table keyed by ``memories.rowid`` for true ANN
candidate retrieval.

Without sqlite-vec, ``Store.search`` falls back to returning all active
rows for in-Python ranking. With it, ``Store.search`` does a real
top-K KNN query and the ranker only re-scores the survivors.

Migration: an existing store that has no ``memories_vec`` table gets
one created on first open, then back-filled from ``memories``. Rows
whose embedding dimension does not match the current embedder's dim
are skipped from the vec table — they're invisible to semantic recall
until ``Memory.reindex()`` rewrites their embedding with the current
embedder.
"""

from __future__ import annotations

import json
import logging
import struct
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Prefer pysqlite3 (bundles a modern SQLite built WITH enable_load_extension)
# over the stdlib sqlite3, which is built without extension support on
# some Python distributions (notably the python.org macOS installer).
# When pysqlite3 isn't installed we fall back to the stdlib — sqlite-vec
# will then only load on Pythons whose stdlib sqlite3 has extensions.
try:
    import pysqlite3 as sqlite3  # type: ignore[import-not-found]
except ImportError:
    import sqlite3  # type: ignore[no-redef]

from hippocamp.types import CompactReport, Inventory, RawRow

log = logging.getLogger(__name__)

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


def _serialize_f32(values: list[float]) -> bytes:
    """Serialise a float list to the little-endian f32 blob sqlite-vec expects.

    We re-implement the trivial pack here so the (de)serialisation does
    not depend on importing sqlite_vec — the call sites that need this
    only run after we've already confirmed vec0 is available, but the
    pure-Python pack keeps the code path simple for tests too.
    """
    return struct.pack(f"<{len(values)}f", *values)


class Store:
    """SQLite store. Pass ``embedding_dim`` for true ANN search.

    ``embedding_dim`` is the dimensionality of the embedder the caller
    will use to insert and query. When provided AND sqlite-vec is
    loadable on this Python's sqlite3, a ``memories_vec(embedding
    FLOAT[dim])`` virtual table is created and used for KNN candidate
    retrieval. When None or unavailable, ``search`` returns all active
    rows (correct but slow at scale) and lets the ranker do everything.
    """

    def __init__(
        self,
        path: str | Path,
        *,
        embedding_dim: int | None = None,
    ) -> None:
        self._path = str(path)
        self._embedding_dim = embedding_dim
        self._conn = sqlite3.connect(self._path, isolation_level=None)
        if self._path != ":memory:":
            self._conn.execute("PRAGMA journal_mode = WAL")
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.executescript(SCHEMA)
        self._vec_enabled = self._try_enable_vec()
        if self._vec_enabled:
            self._maybe_backfill_vec()

    # ----------------------------------------------------------------- vec0

    def _try_enable_vec(self) -> bool:
        """Try to load sqlite-vec and create the vec0 virtual table.

        Returns True iff vec search is available for this store. Reasons
        we may return False: ``sqlite_vec`` not installed, this Python's
        ``sqlite3`` built without ``enable_load_extension`` (notably the
        python.org macOS installer), or ``embedding_dim`` not provided.
        """
        if self._embedding_dim is None:
            return False
        try:
            import sqlite_vec  # type: ignore[import-not-found]
        except ImportError:
            log.info("hippocamp_vec_unavailable: sqlite_vec not installed")
            return False
        if not hasattr(self._conn, "enable_load_extension"):
            log.warning(
                "hippocamp_vec_unavailable: this Python's sqlite3 was built "
                "without enable_load_extension; falling back to naive search"
            )
            return False
        try:
            self._conn.enable_load_extension(True)
            sqlite_vec.load(self._conn)
            self._conn.enable_load_extension(False)
            self._conn.execute(
                f"CREATE VIRTUAL TABLE IF NOT EXISTS memories_vec "
                f"USING vec0(embedding FLOAT[{int(self._embedding_dim)}])"
            )
            return True
        except sqlite3.OperationalError:
            log.warning("hippocamp_vec_unavailable: extension load failed", exc_info=True)
            return False

    def _maybe_backfill_vec(self) -> None:
        """Populate ``memories_vec`` from ``memories`` if it's behind.

        The vec table is empty after the first ever schema apply. It's
        also legitimately empty when the dim has been bumped (e.g.
        embedder switch) and the old vec table was dropped externally.
        In both cases we rebuild from ``memories``, skipping rows whose
        embedding dim doesn't match the current one. Skipped rows remain
        in ``memories`` but stay invisible to semantic recall until
        ``Memory.reindex()`` rewrites them.
        """
        if not self._vec_enabled or self._embedding_dim is None:
            return
        vec_count = self._conn.execute(
            "SELECT COUNT(*) FROM memories_vec"
        ).fetchone()[0]
        active_count = self._conn.execute(
            "SELECT COUNT(*) FROM memories WHERE superseded_at IS NULL"
        ).fetchone()[0]
        if vec_count >= active_count:
            return  # nothing to do (or vec is fully populated)

        rows = self._conn.execute(
            "SELECT rowid, embedding FROM memories WHERE superseded_at IS NULL"
        ).fetchall()
        inserted = 0
        skipped_dim = 0
        for rowid, emb_json in rows:
            already = self._conn.execute(
                "SELECT 1 FROM memories_vec WHERE rowid = ? LIMIT 1", (rowid,)
            ).fetchone()
            if already:
                continue
            try:
                vec = json.loads(emb_json)
            except (TypeError, ValueError):
                skipped_dim += 1
                continue
            if not isinstance(vec, list) or len(vec) != self._embedding_dim:
                skipped_dim += 1
                continue
            self._conn.execute(
                "INSERT INTO memories_vec(rowid, embedding) VALUES (?, ?)",
                (rowid, _serialize_f32([float(x) for x in vec])),
            )
            inserted += 1

        log.info(
            "hippocamp_vec_backfill",
            extra={
                "inserted": inserted,
                "skipped_dim_mismatch": skipped_dim,
                "active_rows": active_count,
                "embedding_dim": self._embedding_dim,
            },
        )

    @property
    def vec_enabled(self) -> bool:
        return self._vec_enabled

    # -------------------------------------------------------------- insert

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
        cur = self._conn.execute(
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
        if self._vec_enabled and self._embedding_dim is not None:
            if len(embedding) != self._embedding_dim:
                log.warning(
                    "hippocamp_insert_skipped_vec: embedding dim mismatch",
                    extra={
                        "expected_dim": self._embedding_dim,
                        "got_dim": len(embedding),
                        "id": id,
                    },
                )
            else:
                self._conn.execute(
                    "INSERT INTO memories_vec(rowid, embedding) VALUES (?, ?)",
                    (cur.lastrowid, _serialize_f32([float(x) for x in embedding])),
                )

    def update_embedding(self, id: str, embedding: list[float]) -> None:
        """Rewrite the embedding for ``id`` in both tables.

        Used by ``Memory.reindex()``. If the new embedding's dim does not
        match the configured vec dim, the JSON column is still rewritten
        but the vec row is removed (and stays out) so recall stays correct.
        """
        emb_json = json.dumps(embedding)
        self._conn.execute(
            "UPDATE memories SET embedding = ? WHERE id = ?",
            (emb_json, id),
        )
        if not self._vec_enabled or self._embedding_dim is None:
            return
        rowid_row = self._conn.execute(
            "SELECT rowid FROM memories WHERE id = ?", (id,)
        ).fetchone()
        if rowid_row is None:
            return
        rowid = rowid_row[0]
        if len(embedding) != self._embedding_dim:
            self._conn.execute("DELETE FROM memories_vec WHERE rowid = ?", (rowid,))
            return
        blob = _serialize_f32([float(x) for x in embedding])
        existing = self._conn.execute(
            "SELECT 1 FROM memories_vec WHERE rowid = ?", (rowid,)
        ).fetchone()
        if existing:
            self._conn.execute(
                "UPDATE memories_vec SET embedding = ? WHERE rowid = ?",
                (blob, rowid),
            )
        else:
            self._conn.execute(
                "INSERT INTO memories_vec(rowid, embedding) VALUES (?, ?)",
                (rowid, blob),
            )

    # ----------------------------------------------------------- superseded

    def mark_superseded(
        self,
        ids: list[str],
        *,
        by: str,
        when: datetime | None = None,
    ) -> None:
        ts = (when or datetime.now(timezone.utc)).isoformat()
        for old_id in ids:
            self._conn.execute(
                "UPDATE memories SET superseded_at = ? WHERE id = ?",
                (ts, old_id),
            )

    # ---------------------------------------------------------------- search

    def search(
        self,
        *,
        query_emb: list[float],
        kinds: list[str] | None,
        candidate_limit: int,
    ) -> list[RawRow]:
        """Return candidate rows for the ranker.

        With vec0 available, runs a real KNN against ``memories_vec``
        and joins back to ``memories`` for row data and the active /
        kind filters. Without vec0, returns *all* active rows in the
        requested kind subset (no LIMIT — correct but slow). The naive
        LIMIT-without-ORDER-BY of the v0.0.1 implementation was buggy:
        it biased toward the oldest insertions, so recent writes never
        reached the ranker.
        """
        if self._vec_enabled and self._embedding_dim is not None and len(
            query_emb
        ) == self._embedding_dim:
            return self._search_vec(query_emb, kinds, candidate_limit)
        return self._search_naive(kinds)

    def _search_vec(
        self,
        query_emb: list[float],
        kinds: list[str] | None,
        candidate_limit: int,
    ) -> list[RawRow]:
        # KNN over the vec table, then join with memories for row data
        # and to apply the active + kind filters in SQL.
        sql = (
            "SELECT m.id, m.kind, m.text, m.created_at, m.last_seen_at, "
            "m.salience, m.metadata, m.embedding "
            "FROM memories_vec v "
            "JOIN memories m ON m.rowid = v.rowid "
            "WHERE v.embedding MATCH ? AND k = ? "
            "AND m.superseded_at IS NULL"
        )
        params: list[Any] = [
            _serialize_f32([float(x) for x in query_emb]),
            int(candidate_limit),
        ]
        if kinds:
            placeholders = ",".join("?" * len(kinds))
            sql += f" AND m.kind IN ({placeholders})"
            params.extend(kinds)
        sql += " ORDER BY v.distance"
        rows = self._conn.execute(sql, params).fetchall()
        return [self._row_from_tuple(r) for r in rows]

    def _search_naive(self, kinds: list[str] | None) -> list[RawRow]:
        sql = (
            "SELECT id, kind, text, created_at, last_seen_at, salience, "
            "metadata, embedding FROM memories WHERE superseded_at IS NULL"
        )
        params: list[Any] = []
        if kinds:
            placeholders = ",".join("?" * len(kinds))
            sql += f" AND kind IN ({placeholders})"
            params.extend(kinds)
        rows = self._conn.execute(sql, params).fetchall()
        return [self._row_from_tuple(r) for r in rows]

    @staticmethod
    def _row_from_tuple(r: tuple) -> RawRow:
        return RawRow(
            id=r[0],
            kind=r[1],
            text=r[2],
            created_at=datetime.fromisoformat(r[3]),
            last_seen_at=datetime.fromisoformat(r[4]),
            salience=r[5],
            metadata=json.loads(r[6]),
            embedding=json.loads(r[7]),
        )

    # ------------------------------------------------------ misc maintenance

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

    def tombstone(self, id: str, *, when: datetime | None = None) -> None:
        """Mark a memory inactive (soft-delete). Preserves the row so the
        event log remains the source of truth and replay is deterministic.

        The vec entry is left in place: ``search`` filters via the join on
        ``superseded_at IS NULL`` so a tombstoned row is never returned.
        Leaving the vec row avoids a write per tombstone; ``compact`` can
        prune the vec table later if it grows.
        """
        ts = (when or datetime.now(timezone.utc)).isoformat()
        self._conn.execute(
            "UPDATE memories SET superseded_at = ? WHERE id = ?",
            (ts, id),
        )

    def wipe(self) -> None:
        """Drop all rows. Used by `Memory.replay()` before rebuilding."""
        self._conn.execute("DELETE FROM memories")
        if self._vec_enabled:
            self._conn.execute("DELETE FROM memories_vec")

    def episodes_since(self, cutoff: datetime, *, limit: int) -> list[RawRow]:
        """Active episodes created at or after `cutoff`, oldest first.

        Used by `reflect()` to find episodes that arrived since the last
        consolidation pass.
        """
        rows = self._conn.execute(
            "SELECT id, kind, text, created_at, last_seen_at, salience, "
            "metadata, embedding FROM memories "
            "WHERE kind = 'episode' AND superseded_at IS NULL "
            "AND created_at >= ? "
            "ORDER BY created_at ASC LIMIT ?",
            (cutoff.isoformat(), limit),
        ).fetchall()
        return [self._row_from_tuple(r) for r in rows]

    def list_active_before(self, cutoff: datetime) -> list[str]:
        """Ids of active (non-superseded) memories created before `cutoff`."""
        rows = self._conn.execute(
            "SELECT id FROM memories "
            "WHERE created_at < ? AND superseded_at IS NULL",
            (cutoff.isoformat(),),
        ).fetchall()
        return [r[0] for r in rows]

    def expire_before(self, cutoff: datetime) -> int:
        """Tombstone all active memories created before `cutoff`. Returns count."""
        ids = self.list_active_before(cutoff)
        ts = datetime.now(timezone.utc).isoformat()
        for mem_id in ids:
            self._conn.execute(
                "UPDATE memories SET superseded_at = ? WHERE id = ?",
                (ts, mem_id),
            )
        return len(ids)

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
