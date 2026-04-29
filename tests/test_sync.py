"""Tests for cross-machine sync: merge_foreign_events, replay, and the
shape of `hippocamp sync` flows.

The rsync-based push/pull commands are thin subprocess wrappers and
aren't unit-tested here — they're covered by manual integration testing.
The merge logic, which is the actual interesting code, is tested
end-to-end with two real Memory instances pretending to be two devices.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from hippocamp import Memory
from hippocamp.embedders import HashEmbedder
from hippocamp.events import Event, EventLog, EventOp
from hippocamp.sync import merge_foreign_events


def _new_memory(store_dir: Path, device_id: str) -> Memory:
    return Memory(
        path=str(store_dir / "store.db"),
        embedder=HashEmbedder(),
        device_id=device_id,
    )


# ------------------------------------------------------------------ merge


def test_merge_from_single_jsonl_file(tmp_path):
    """Smallest case: a single foreign device file."""
    local_dir = tmp_path / "local"
    local_dir.mkdir()
    mem = _new_memory(local_dir, "laptop")
    mem.observe("local event")

    # Build a foreign device file by hand
    foreign_file = tmp_path / "desktop.jsonl"
    foreign_file.write_text(
        Event(
            id="ev_foreigneventid01",
            ts="2026-04-30T00:00:00+00:00",
            device="desktop",
            op=EventOp.OBSERVE,
            mem_id="ep_remote1",
            text="event from peer",
        ).model_dump_json() + "\n"
    )

    report = merge_foreign_events(
        foreign_path=foreign_file,
        local_events_dir=mem.events_dir,
        local_meta=mem.meta,
        local_device_id=mem.device_id,
    )
    assert report.total_events_added == 1
    assert report.files_skipped == 0

    # The peer's file now lives next to ours
    assert (mem.events_dir / "desktop.jsonl").exists()


def test_merge_from_full_store_directory(tmp_path):
    """Common case: another machine's whole `~/.hippocamp` directory."""
    # Build "peer" store
    peer_dir = tmp_path / "peer"
    peer_dir.mkdir()
    peer = _new_memory(peer_dir, "desktop")
    peer.observe("event A from peer")
    peer.assert_fact("a fact from peer")
    peer.close()

    # Build "local" store
    local_dir = tmp_path / "local"
    local_dir.mkdir()
    local = _new_memory(local_dir, "laptop")
    local.observe("local event")

    report = merge_foreign_events(
        foreign_path=peer_dir,
        local_events_dir=local.events_dir,
        local_meta=local.meta,
        local_device_id=local.device_id,
    )
    assert report.total_events_added == 2

    n = local.replay()
    assert n == 3  # local event + 2 from peer

    rows = local._store._conn.execute(
        "SELECT id, text FROM memories ORDER BY created_at"
    ).fetchall()
    texts = {r[1] for r in rows}
    assert texts == {"local event", "event A from peer", "a fact from peer"}


def test_merge_is_idempotent(tmp_path):
    """Running merge twice should not duplicate events."""
    peer_dir = tmp_path / "peer"
    peer_dir.mkdir()
    peer = _new_memory(peer_dir, "desktop")
    peer.observe("peer event")
    peer.close()

    local_dir = tmp_path / "local"
    local_dir.mkdir()
    local = _new_memory(local_dir, "laptop")

    r1 = merge_foreign_events(
        foreign_path=peer_dir,
        local_events_dir=local.events_dir,
        local_meta=local.meta,
        local_device_id=local.device_id,
    )
    r2 = merge_foreign_events(
        foreign_path=peer_dir,
        local_events_dir=local.events_dir,
        local_meta=local.meta,
        local_device_id=local.device_id,
    )
    assert r1.total_events_added == 1
    assert r2.total_events_added == 0  # already present


def test_merge_skips_own_device_file(tmp_path):
    """We must never overwrite our own device file from a foreign source."""
    local_dir = tmp_path / "local"
    local_dir.mkdir()
    local = _new_memory(local_dir, "laptop")
    own_id = local.observe("real local event")
    local.close()

    # Construct a foreign source with a file named exactly like ours
    foreign_dir = tmp_path / "foreign"
    foreign_events = foreign_dir / "events"
    foreign_events.mkdir(parents=True)
    bogus = foreign_events / "laptop.jsonl"
    bogus.write_text(
        Event(
            id="ev_bogus000000000",
            ts="2030-01-01T00:00:00+00:00",
            device="laptop",
            op=EventOp.OBSERVE,
            mem_id="ep_BOGUS",
            text="this should not land in our log",
        ).model_dump_json() + "\n"
    )
    (foreign_dir / "meta.json").write_text(
        local.meta.model_dump_json()
    )

    report = merge_foreign_events(
        foreign_path=foreign_dir,
        local_events_dir=local.events_dir,
        local_meta=local.meta,
        local_device_id=local.device_id,
    )
    assert report.files_skipped == 1

    # Our file untouched: real event still there, bogus event NOT there
    own_file_text = (local.events_dir / "laptop.jsonl").read_text()
    assert own_id in own_file_text
    assert "ep_BOGUS" not in own_file_text


def test_merge_rejects_embedder_mismatch(tmp_path):
    """Foreign meta.json with a different embedder must be rejected."""
    local_dir = tmp_path / "local"
    local_dir.mkdir()
    local = _new_memory(local_dir, "laptop")

    # Build a foreign store dir with a deliberately different embedder
    peer_dir = tmp_path / "peer"
    (peer_dir / "events").mkdir(parents=True)
    (peer_dir / "meta.json").write_text(
        json.dumps({
            "embedder": "some-other-embedder",
            "store_id": "abc",
            "schema_version": 1,
            "created_at": "2026-04-29T00:00:00+00:00",
        })
    )

    with pytest.raises(RuntimeError, match="Embedder mismatch"):
        merge_foreign_events(
            foreign_path=peer_dir,
            local_events_dir=local.events_dir,
            local_meta=local.meta,
            local_device_id=local.device_id,
        )


def test_merge_partial_overlap_appends_only_new(tmp_path):
    """If we already have some of a peer's events, only new ones get added."""
    peer_dir = tmp_path / "peer"
    peer_dir.mkdir()
    peer = _new_memory(peer_dir, "desktop")
    peer.observe("first peer event")
    peer.close()

    local_dir = tmp_path / "local"
    local_dir.mkdir()
    local = _new_memory(local_dir, "laptop")

    # First sync: peer has 1 event, we add it
    r1 = merge_foreign_events(
        foreign_path=peer_dir,
        local_events_dir=local.events_dir,
        local_meta=local.meta,
        local_device_id=local.device_id,
    )
    assert r1.total_events_added == 1

    # Peer adds another event
    peer = _new_memory(peer_dir, "desktop")
    peer.observe("second peer event")
    peer.close()

    # Second sync: only the new event gets added
    r2 = merge_foreign_events(
        foreign_path=peer_dir,
        local_events_dir=local.events_dir,
        local_meta=local.meta,
        local_device_id=local.device_id,
    )
    assert r2.total_events_added == 1
    assert r2.events_added["desktop.jsonl"] == 1


# ----------------------------------------------------- end-to-end (two devs)


def test_two_device_sync_round_trip(tmp_path):
    """The headline test: two devices, sync events, identical caches."""
    laptop_dir = tmp_path / "laptop"
    desktop_dir = tmp_path / "desktop"
    laptop_dir.mkdir()
    desktop_dir.mkdir()

    laptop = _new_memory(laptop_dir, "laptop")
    desktop = _new_memory(desktop_dir, "desktop")

    laptop_ep = laptop.observe("user wants to deploy to GCP")
    desktop_pref = desktop.assert_preference("prefers terse replies", strength=0.9)

    # Sync laptop → desktop
    merge_foreign_events(
        foreign_path=laptop_dir,
        local_events_dir=desktop.events_dir,
        local_meta=desktop.meta,
        local_device_id=desktop.device_id,
    )
    desktop.replay()

    # Sync desktop → laptop
    merge_foreign_events(
        foreign_path=desktop_dir,
        local_events_dir=laptop.events_dir,
        local_meta=laptop.meta,
        local_device_id=laptop.device_id,
    )
    laptop.replay()

    # Both devices should now have both memories
    for mem in (laptop, desktop):
        rows = mem._store._conn.execute(
            "SELECT id FROM memories WHERE superseded_at IS NULL ORDER BY id"
        ).fetchall()
        ids = {r[0] for r in rows}
        assert ids == {laptop_ep, desktop_pref}, (
            f"device {mem.device_id} has {ids} not the expected pair"
        )
