"""Tests for the event-log architecture: events.jsonl, meta.json, and replay.

These tests prove the central invariant of the v0.3.0 architecture:
the SQLite cache is fully derivable from the event log. If you delete
the cache and call `replay()`, you get back the exact same active state.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from hippocamp import Memory
from hippocamp.embedders import HashEmbedder
from hippocamp.events import EventLog, EventOp


def _new_memory(tmp_path: Path) -> Memory:
    return Memory(
        path=str(tmp_path / "store.db"),
        embedder=HashEmbedder(),
        device_id="dev_test",
    )


def _active_state(mem: Memory) -> list[tuple]:
    """Snapshot of active rows in the cache, for equivalence comparisons."""
    rows = mem._store._conn.execute(
        "SELECT id, kind, text, created_at, last_seen_at, superseded_at, "
        "salience, metadata "
        "FROM memories ORDER BY id"
    ).fetchall()
    return [tuple(r) for r in rows]


# ----------------------------------------------------------------- meta.json


def test_meta_json_created_on_first_open(tmp_path):
    mem = _new_memory(tmp_path)
    meta_path = tmp_path / "meta.json"
    assert meta_path.exists()
    data = json.loads(meta_path.read_text())
    assert data["embedder"] == "hash-32"
    assert data["schema_version"] == 1
    assert "store_id" in data


def test_embedder_mismatch_is_rejected(tmp_path):
    _new_memory(tmp_path)  # creates meta.json with hash-32

    # Try to open the same store with a different embedder
    class FakeOtherEmbedder:
        name = "fake-other"
        def __call__(self, text):
            return [0.0] * 32

    with pytest.raises(RuntimeError, match="Embedder mismatch"):
        Memory(
            path=str(tmp_path / "store.db"),
            embedder=FakeOtherEmbedder(),
            device_id="dev_test",
        )


# --------------------------------------------------------------- events.jsonl


def test_observe_appends_event(tmp_path):
    mem = _new_memory(tmp_path)
    ep_id = mem.observe("user wants to deploy to GCP", actors=["user"])

    log = EventLog(tmp_path / "events.jsonl")
    events = list(log.read_all())
    assert len(events) == 1
    e = events[0]
    assert e.op == EventOp.OBSERVE
    assert e.mem_id == ep_id
    assert e.text == "user wants to deploy to GCP"
    assert e.actors == ["user"]
    assert e.device == "dev_test"


def test_assert_fact_appends_event_with_supersedes(tmp_path):
    mem = _new_memory(tmp_path)
    old = mem.assert_fact("project uses Python 3.12")
    new = mem.assert_fact("project uses Python 3.13", supersedes=[old])

    events = list(EventLog(tmp_path / "events.jsonl").read_all())
    assert len(events) == 2
    assert events[1].op == EventOp.ASSERT_FACT
    assert events[1].mem_id == new
    assert events[1].supersedes == [old]


def test_assert_preference_appends_event(tmp_path):
    mem = _new_memory(tmp_path)
    pid = mem.assert_preference("prefers terse replies", strength=0.9)

    events = list(EventLog(tmp_path / "events.jsonl").read_all())
    assert len(events) == 1
    assert events[0].op == EventOp.ASSERT_PREF
    assert events[0].mem_id == pid
    assert events[0].strength == 0.9


def test_forget_appends_event_and_tombstones(tmp_path):
    mem = _new_memory(tmp_path)
    eid = mem.observe("temporary thought")
    mem.forget(eid)

    events = list(EventLog(tmp_path / "events.jsonl").read_all())
    assert len(events) == 2
    assert events[1].op == EventOp.FORGET
    assert events[1].mem_id == eid

    # Forget should tombstone, not hard-delete; the row still exists with
    # superseded_at set.
    row = mem._store._conn.execute(
        "SELECT superseded_at FROM memories WHERE id = ?", (eid,)
    ).fetchone()
    assert row is not None
    assert row[0] is not None


# ---------------------------------------------------- replay round-trip


def test_replay_rebuilds_identical_cache(tmp_path):
    """The central invariant: cache is fully derivable from the event log."""
    mem = _new_memory(tmp_path)

    ep_id = mem.observe("user asked about deploying to GCP", actors=["user"])
    fact_id = mem.assert_fact("project uses Python 3.13", evidence=[ep_id])
    pref_id = mem.assert_preference("prefers terse replies", strength=0.9)
    old_fact = mem.assert_fact("uses Python 3.12")
    new_fact = mem.assert_fact("uses Python 3.13", supersedes=[old_fact])
    mem.forget(ep_id)

    state_before = _active_state(mem)

    # Wipe the cache; events.jsonl + meta.json remain on disk
    mem.close()
    (tmp_path / "store.db").unlink()
    for sidecar in ("store.db-shm", "store.db-wal"):
        p = tmp_path / sidecar
        if p.exists():
            p.unlink()

    # Reopen and replay
    mem2 = _new_memory(tmp_path)
    n = mem2.replay()
    assert n == 6, f"expected 6 events, got {n}"

    state_after = _active_state(mem2)
    assert state_before == state_after, "replay produced a different cache"


def test_replay_preserves_inspect_counts(tmp_path):
    mem = _new_memory(tmp_path)
    mem.observe("ep1")
    mem.observe("ep2")
    mem.assert_fact("a fact")
    mem.assert_preference("a pref")
    forgotten = mem.observe("will be forgotten")
    mem.forget(forgotten)

    inv_before = mem.inspect()

    mem.close()
    (tmp_path / "store.db").unlink()
    for sidecar in ("store.db-shm", "store.db-wal"):
        p = tmp_path / sidecar
        if p.exists():
            p.unlink()

    mem2 = _new_memory(tmp_path)
    mem2.replay()
    inv_after = mem2.inspect()

    assert inv_before.episodes == inv_after.episodes
    assert inv_before.facts == inv_after.facts
    assert inv_before.preferences == inv_after.preferences


def test_replay_preserves_recall_ranking(tmp_path):
    mem = _new_memory(tmp_path)
    a = mem.observe("the cat sat on the mat")
    b = mem.observe("a totally unrelated fact about quarks")
    c = mem.observe("the cat is fluffy")

    hits_before = mem.recall("cat", limit=3)
    ids_before = [h.id for h in hits_before]

    mem.close()
    (tmp_path / "store.db").unlink()
    for sidecar in ("store.db-shm", "store.db-wal"):
        p = tmp_path / sidecar
        if p.exists():
            p.unlink()

    mem2 = _new_memory(tmp_path)
    mem2.replay()
    hits_after = mem2.recall("cat", limit=3)
    ids_after = [h.id for h in hits_after]

    assert ids_before == ids_after, (
        f"ranking differs after replay: {ids_before} != {ids_after}"
    )


# --------------------------------------------------- migration / bootstrap


def test_bootstrap_creates_events_from_existing_cache(tmp_path):
    """Opening a pre-v0.3 store (cache rows, no events) bootstraps the log.

    This is the migration path for users upgrading from v0.1. Without
    it, calling replay() on their existing data would wipe it.
    """
    # Simulate a pre-v0.3 store: write rows directly to the cache, no
    # events.jsonl, no meta.json.
    db_path = tmp_path / "store.db"
    pre_mem = Memory(path=":memory:", embedder=HashEmbedder())  # to populate
    # Write directly via Store to skip event emission, then move to disk:
    from hippocamp.store import Store
    s = Store(str(db_path))
    s._conn.execute(
        "INSERT INTO memories (id, kind, text, created_at, last_seen_at, "
        "metadata, embedding) VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("ep_legacy", "episode", "legacy episode", "2026-04-01T00:00:00+00:00",
         "2026-04-01T00:00:00+00:00", "{}", "[]"),
    )
    s._conn.execute(
        "INSERT INTO memories (id, kind, text, created_at, last_seen_at, "
        "metadata, embedding) VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("fa_legacy", "fact", "legacy fact", "2026-04-02T00:00:00+00:00",
         "2026-04-02T00:00:00+00:00", '{"evidence": []}', "[]"),
    )
    s.close()

    # Now open with the new architecture
    mem = Memory(path=str(db_path), embedder=HashEmbedder(), device_id="dev_test")

    # events.jsonl should now exist with bootstrapped events
    events = list(EventLog(tmp_path / "events.jsonl").read_all())
    assert len(events) == 2
    ids = {e.mem_id for e in events}
    assert ids == {"ep_legacy", "fa_legacy"}

    # And replay should now be safe — it should rebuild what was there.
    n = mem.replay()
    assert n == 2
    rows = mem._store._conn.execute(
        "SELECT id FROM memories ORDER BY id"
    ).fetchall()
    assert {r[0] for r in rows} == {"ep_legacy", "fa_legacy"}


def test_bootstrap_does_not_run_on_subsequent_opens(tmp_path):
    """Bootstrap should only fire on the very first v0.3+ open."""
    # First open (creates meta.json, no rows so no events)
    mem1 = Memory(path=str(tmp_path / "store.db"), embedder=HashEmbedder(), device_id="d1")
    mem1.observe("a thing")
    mem1.close()

    events_before = (tmp_path / "events.jsonl").read_text()

    # Second open should not re-bootstrap
    mem2 = Memory(path=str(tmp_path / "store.db"), embedder=HashEmbedder(), device_id="d1")
    events_after = (tmp_path / "events.jsonl").read_text()
    assert events_before == events_after


# ----------------------------------------------------- in-memory mode


def test_in_memory_does_not_create_events_log(tmp_path, monkeypatch):
    # Force HOME to tmp_path so device.json (if created) lands in tmp
    monkeypatch.setenv("HOME", str(tmp_path))
    mem = Memory(path=":memory:", embedder=HashEmbedder())
    mem.observe("ephemeral")
    assert mem.events_path is None
    assert mem.meta is None
    with pytest.raises(RuntimeError, match="requires an on-disk store"):
        mem.replay()
