"""Tests for the event-log architecture: events/, meta.json, and replay.

These tests prove the central invariant of the v0.3.0 architecture:
the SQLite cache is fully derivable from the per-device event logs. If
you delete the cache and call `replay()`, you get back the exact same
active state.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from hippocamp import Memory
from hippocamp.embedders import HashEmbedder
from hippocamp.events import Event, EventLog, EventOp


def _new_memory(tmp_path: Path, device_id: str = "dev_test") -> Memory:
    return Memory(
        path=str(tmp_path / "store.db"),
        embedder=HashEmbedder(),
        device_id=device_id,
    )


def _active_state(mem: Memory) -> list[tuple]:
    """Snapshot of cache rows, used for equivalence comparisons."""
    rows = mem._store._conn.execute(
        "SELECT id, kind, text, created_at, last_seen_at, superseded_at, "
        "salience, metadata "
        "FROM memories ORDER BY id"
    ).fetchall()
    return [tuple(r) for r in rows]


# ----------------------------------------------------------------- meta.json


def test_meta_json_created_on_first_open(tmp_path):
    _new_memory(tmp_path)
    meta_path = tmp_path / "meta.json"
    assert meta_path.exists()
    data = json.loads(meta_path.read_text())
    assert data["embedder"] == "hash-32"
    assert data["schema_version"] == 1
    assert "store_id" in data


def test_embedder_mismatch_is_rejected(tmp_path):
    _new_memory(tmp_path)

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


# --------------------------------------------------- per-device event files


def test_observe_writes_only_to_own_device_file(tmp_path):
    mem = _new_memory(tmp_path, device_id="dev_test")
    ep_id = mem.observe("user wants to deploy to GCP", actors=["user"])

    own_file = tmp_path / "events" / "dev_test.jsonl"
    assert own_file.exists()

    log = EventLog(tmp_path / "events", "dev_test")
    events = list(log.read_all())
    assert len(events) == 1
    assert events[0].mem_id == ep_id
    assert events[0].device == "dev_test"


def test_each_device_writes_to_separate_file(tmp_path):
    """The clean architectural invariant: one writer per file, ever."""
    mem_a = _new_memory(tmp_path, device_id="laptop")
    mem_a.observe("event from laptop")
    mem_a.close()

    mem_b = _new_memory(tmp_path, device_id="desktop")
    mem_b.observe("event from desktop")
    mem_b.close()

    events_dir = tmp_path / "events"
    files = sorted(p.name for p in events_dir.glob("*.jsonl"))
    assert files == ["desktop.jsonl", "laptop.jsonl"]


def test_read_all_merges_events_across_devices_in_time_order(tmp_path):
    # Pre-populate two device files manually (simulating a sync'd state)
    events_dir = tmp_path / "events"
    events_dir.mkdir(parents=True)
    EventLog(events_dir, "laptop").append(
        Event(
            id="ev_aaaaaaaaaaaaaaaa",
            ts="2026-04-01T00:00:00+00:00",
            device="laptop",
            op=EventOp.OBSERVE,
            mem_id="ep_lap1",
            text="from laptop early",
        )
    )
    EventLog(events_dir, "desktop").append(
        Event(
            id="ev_bbbbbbbbbbbbbbbb",
            ts="2026-04-01T00:00:01+00:00",
            device="desktop",
            op=EventOp.OBSERVE,
            mem_id="ep_des1",
            text="from desktop later",
        )
    )

    log = EventLog(events_dir, "laptop")
    ordered = [e.mem_id for e in log.read_all()]
    assert ordered == ["ep_lap1", "ep_des1"]


def test_assert_fact_appends_event_with_supersedes(tmp_path):
    mem = _new_memory(tmp_path)
    old = mem.assert_fact("project uses Python 3.12")
    new = mem.assert_fact("project uses Python 3.13", supersedes=[old])

    log = EventLog(tmp_path / "events", "dev_test")
    events = list(log.read_all())
    assert len(events) == 2
    assert events[1].op == EventOp.ASSERT_FACT
    assert events[1].mem_id == new
    assert events[1].supersedes == [old]


def test_assert_preference_appends_event(tmp_path):
    mem = _new_memory(tmp_path)
    pid = mem.assert_preference("prefers terse replies", strength=0.9)

    log = EventLog(tmp_path / "events", "dev_test")
    events = list(log.read_all())
    assert len(events) == 1
    assert events[0].op == EventOp.ASSERT_PREF
    assert events[0].mem_id == pid
    assert events[0].strength == 0.9


def test_forget_appends_event_and_tombstones(tmp_path):
    mem = _new_memory(tmp_path)
    eid = mem.observe("temporary thought")
    mem.forget(eid)

    log = EventLog(tmp_path / "events", "dev_test")
    events = list(log.read_all())
    assert len(events) == 2
    assert events[1].op == EventOp.FORGET
    assert events[1].mem_id == eid

    row = mem._store._conn.execute(
        "SELECT superseded_at FROM memories WHERE id = ?", (eid,)
    ).fetchone()
    assert row is not None
    assert row[0] is not None


# ----------------------------------------------------- replay round-trip


def test_replay_rebuilds_identical_cache(tmp_path):
    mem = _new_memory(tmp_path)

    ep_id = mem.observe("user asked about deploying to GCP", actors=["user"])
    fact_id = mem.assert_fact("project uses Python 3.13", evidence=[ep_id])
    pref_id = mem.assert_preference("prefers terse replies", strength=0.9)
    old_fact = mem.assert_fact("uses Python 3.12")
    new_fact = mem.assert_fact("uses Python 3.13", supersedes=[old_fact])
    mem.forget(ep_id)

    state_before = _active_state(mem)

    mem.close()
    (tmp_path / "store.db").unlink()
    for sidecar in ("store.db-shm", "store.db-wal"):
        p = tmp_path / sidecar
        if p.exists():
            p.unlink()

    mem2 = _new_memory(tmp_path)
    n = mem2.replay()
    assert n == 6, f"expected 6 events, got {n}"
    assert _active_state(mem2) == state_before


def test_replay_picks_up_a_newly_synced_device_file(tmp_path):
    """Simulates: a peer device's events file lands in events/ via sync.

    After replay, this device's cache should include the peer's events.
    """
    # This device writes some events
    mem = _new_memory(tmp_path, device_id="laptop")
    laptop_ep = mem.observe("event from laptop")
    mem.close()

    # A peer's events file is dropped into events/ (e.g. by Dropbox)
    peer_log = EventLog(tmp_path / "events", "desktop")
    peer_log.append(
        Event(
            id="ev_peerpeerpeerpeer",
            ts="2026-05-01T00:00:00+00:00",
            device="desktop",
            op=EventOp.OBSERVE,
            mem_id="ep_desk1",
            text="event from peer desktop",
        )
    )

    # Wipe local cache and replay; we should see both events
    (tmp_path / "store.db").unlink()
    for sidecar in ("store.db-shm", "store.db-wal"):
        p = tmp_path / sidecar
        if p.exists():
            p.unlink()

    mem2 = _new_memory(tmp_path, device_id="laptop")
    n = mem2.replay()
    assert n == 2

    rows = mem2._store._conn.execute(
        "SELECT id FROM memories ORDER BY id"
    ).fetchall()
    ids = {r[0] for r in rows}
    assert ids == {laptop_ep, "ep_desk1"}


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

    assert ids_before == ids_after


# --------------------------------------------------- migration / bootstrap


def test_bootstrap_creates_events_from_existing_cache(tmp_path):
    db_path = tmp_path / "store.db"

    # Simulate a pre-v0.3 store: rows in cache, no events, no meta
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

    mem = Memory(path=str(db_path), embedder=HashEmbedder(), device_id="dev_test")

    own_file = tmp_path / "events" / "dev_test.jsonl"
    assert own_file.exists()
    events = list(EventLog(tmp_path / "events", "dev_test").read_all())
    assert {e.mem_id for e in events} == {"ep_legacy", "fa_legacy"}

    n = mem.replay()
    assert n == 2
    rows = mem._store._conn.execute(
        "SELECT id FROM memories ORDER BY id"
    ).fetchall()
    assert {r[0] for r in rows} == {"ep_legacy", "fa_legacy"}


def test_bootstrap_does_not_run_on_subsequent_opens(tmp_path):
    mem1 = _new_memory(tmp_path)
    mem1.observe("a thing")
    mem1.close()

    own_file = tmp_path / "events" / "dev_test.jsonl"
    before = own_file.read_text()

    _new_memory(tmp_path)
    after = own_file.read_text()
    assert before == after


def test_legacy_single_file_log_is_split_by_device(tmp_path):
    """If a slice-1 events.jsonl exists, it gets split into events/<device>.jsonl."""
    legacy = tmp_path / "events.jsonl"
    legacy.write_text(
        Event(
            id="ev_aaaaaaaaaaaaaaaa",
            ts="2026-04-01T00:00:00+00:00",
            device="laptop",
            op=EventOp.OBSERVE,
            mem_id="ep_lap1",
            text="laptop event",
        ).model_dump_json() + "\n" +
        Event(
            id="ev_bbbbbbbbbbbbbbbb",
            ts="2026-04-02T00:00:00+00:00",
            device="desktop",
            op=EventOp.OBSERVE,
            mem_id="ep_des1",
            text="desktop event",
        ).model_dump_json() + "\n"
    )

    Memory(path=str(tmp_path / "store.db"), embedder=HashEmbedder(), device_id="laptop")

    # Legacy file gone, per-device files present
    assert not legacy.exists()
    assert (tmp_path / "events" / "laptop.jsonl").exists()
    assert (tmp_path / "events" / "desktop.jsonl").exists()


# ----------------------------------------------------- in-memory mode


def test_in_memory_does_not_create_events_log(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    mem = Memory(path=":memory:", embedder=HashEmbedder())
    mem.observe("ephemeral")
    assert mem.events_dir is None
    assert mem.meta is None
    with pytest.raises(RuntimeError, match="requires an on-disk store"):
        mem.replay()
