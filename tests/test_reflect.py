"""Tests for `Memory.reflect()` — LLM-driven memory consolidation."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from hippocamp import Memory
from hippocamp.embedders import HashEmbedder
from hippocamp.reflect import _ReflectLock, run_reflection


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


class ScriptedLLM:
    """Returns a sequence of pre-canned JSON strings, in order."""

    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self.calls: list[str] = []

    def complete(self, prompt: str, *, system: str | None = None) -> str:
        self.calls.append(prompt)
        if not self._responses:
            raise RuntimeError("ScriptedLLM exhausted")
        return self._responses.pop(0)


def _episodes_in_prompt(prompt: str) -> list[str]:
    import re
    return re.findall(r"\[(ep_[a-f0-9]+)\]", prompt)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mem_factory(tmp_path):
    """Build a fresh on-disk Memory with HashEmbedder (deterministic, fast)."""

    def _build(llm=None):
        return Memory(
            path=str(tmp_path / "store"),
            embedder=HashEmbedder(),
            llm=llm,
        )

    return _build


def _seed_episodes(mem: Memory, n: int, prefix: str = "thing") -> list[str]:
    ids = []
    for i in range(n):
        ids.append(mem.observe(f"User mentioned {prefix} {i}, working at Benefex"))
    return ids


# ---------------------------------------------------------------------------
# Cases
# ---------------------------------------------------------------------------


def test_no_episodes_yields_skip_note(mem_factory):
    llm = ScriptedLLM([])
    mem = mem_factory(llm=llm)
    report = mem.reflect(since=datetime.now(timezone.utc) - timedelta(days=1))
    assert report.episodes_processed == 0
    assert report.new_facts == 0
    assert "Skipped" in report.notes
    assert llm.calls == []  # LLM never called


def test_below_min_episodes_skips(mem_factory):
    llm = ScriptedLLM([])
    mem = mem_factory(llm=llm)
    _seed_episodes(mem, 3)  # below default min_episodes=5
    report = run_reflection(
        mem, llm,
        since=datetime.now(timezone.utc) - timedelta(days=30),
        min_episodes=5,
    )
    assert report.episodes_processed == 3
    assert report.new_facts == 0
    assert llm.calls == []


def test_happy_path_writes_facts_prefs_reflections(mem_factory):
    llm = ScriptedLLM([
        json.dumps({
            "facts": [{"text": "User works at Benefex.", "evidence": ["__FILL__"]}],
            "preferences": [{"text": "User likes concise output.", "evidence": ["__FILL__"]}],
            "reflections": [{"text": "User probes memory features.", "evidence": ["__FILL__"]}],
        })
    ])
    mem = mem_factory(llm=llm)
    eids = _seed_episodes(mem, 6)

    # Patch the response so evidence ids match real episodes
    def fill(prompt, *, system=None):
        ids = _episodes_in_prompt(prompt)
        return json.dumps({
            "facts": [{"text": "User works at Benefex.", "evidence": ids[:2]}],
            "preferences": [{"text": "User likes concise output.", "evidence": ids[:1]}],
            "reflections": [{"text": "User probes memory features.", "evidence": ids}],
        })
    llm.complete = fill

    report = mem.reflect(since=datetime.now(timezone.utc) - timedelta(days=30))
    assert report.episodes_processed == 6
    assert report.new_facts == 1
    assert report.new_preferences == 1
    assert report.new_reflections == 1
    assert report.superseded == 0

    inv = mem.inspect()
    assert inv.facts == 1
    assert inv.preferences == 1
    assert inv.reflections == 1


def test_dedup_into_supersede(mem_factory):
    """When a near-duplicate fact already exists, the new fact supersedes it."""

    mem = mem_factory(llm=None)
    # Pre-seed an existing fact
    old_id = mem.assert_fact("User works at Benefex Limited.")

    # Now run reflection that produces a near-identical fact.
    def reply(prompt, *, system=None):
        ids = _episodes_in_prompt(prompt)
        return json.dumps({
            "facts": [{"text": "User works at Benefex Limited.", "evidence": ids[:1]}],
            "preferences": [],
            "reflections": [],
        })

    llm = ScriptedLLM([])
    llm.complete = reply
    mem._llm = llm  # type: ignore[attr-defined]

    _seed_episodes(mem, 6, prefix="benefex")
    report = mem.reflect(since=datetime.now(timezone.utc) - timedelta(days=30))

    assert report.new_facts == 1
    assert report.superseded == 1

    # Old fact is now superseded; recall returns only the new one.
    hits = mem.recall("Benefex", kinds=["fact"], limit=5)
    ids = [h.id for h in hits]
    assert old_id not in ids


def test_hallucinated_evidence_is_dropped(mem_factory):
    """Items whose evidence ids aren't in the batch are silently dropped."""
    def reply(prompt, *, system=None):
        ids = _episodes_in_prompt(prompt)
        return json.dumps({
            "facts": [
                {"text": "Real fact.", "evidence": ids[:1]},
                {"text": "Hallucinated fact.", "evidence": ["ep_NOTREAL"]},
            ],
            "preferences": [],
            "reflections": [],
        })

    llm = ScriptedLLM([])
    llm.complete = reply
    mem = mem_factory(llm=llm)
    _seed_episodes(mem, 6)

    report = mem.reflect(since=datetime.now(timezone.utc) - timedelta(days=30))
    assert report.new_facts == 1  # hallucinated one dropped


def test_malformed_json_retries_then_aborts(mem_factory):
    """Bad JSON triggers one retry; a second failure raises RuntimeError."""
    llm = ScriptedLLM([
        "this is not JSON at all",
        "still not JSON",
    ])
    mem = mem_factory(llm=llm)
    _seed_episodes(mem, 6)

    with pytest.raises(RuntimeError, match="LLM did not return valid JSON"):
        mem.reflect(since=datetime.now(timezone.utc) - timedelta(days=30))

    assert len(llm.calls) == 2


def test_lockfile_blocks_concurrent_run(tmp_path):
    """A held lockfile causes reflect() to refuse."""
    store_dir = tmp_path / "store"
    store_dir.mkdir()
    (store_dir / ".reflect.lock").write_text("12345 running\n")

    lock = _ReflectLock(store_dir)
    with pytest.raises(RuntimeError, match="locked by another process"):
        lock.acquire()


def test_stale_lockfile_is_overridden(tmp_path):
    """A lockfile older than 1h is treated as stale and overwritten."""
    import os
    store_dir = tmp_path / "store"
    store_dir.mkdir()
    lock_path = store_dir / ".reflect.lock"
    lock_path.write_text("12345 stale\n")
    # Backdate it 2 hours
    old = (datetime.now(timezone.utc) - timedelta(hours=2)).timestamp()
    os.utime(lock_path, (old, old))

    lock = _ReflectLock(store_dir)
    lock.acquire()  # should not raise
    lock.release()


def test_last_reflect_at_persisted(mem_factory):
    """A successful reflection updates meta.last_reflect_at."""
    def reply(prompt, *, system=None):
        ids = _episodes_in_prompt(prompt)
        return json.dumps({
            "facts": [{"text": "A fact.", "evidence": ids[:1]}],
            "preferences": [],
            "reflections": [],
        })

    llm = ScriptedLLM([])
    llm.complete = reply
    mem = mem_factory(llm=llm)
    _seed_episodes(mem, 6)

    assert mem.last_reflect_at is None
    mem.reflect(since=datetime.now(timezone.utc) - timedelta(days=30))
    assert mem.last_reflect_at is not None
    assert (datetime.now(timezone.utc) - mem.last_reflect_at) < timedelta(seconds=10)


def test_failed_reflection_does_not_advance_cutoff(mem_factory):
    """Cutoff isn't advanced when LLM call fails — next run retries the same window."""
    llm = ScriptedLLM(["bad", "still bad"])
    mem = mem_factory(llm=llm)
    _seed_episodes(mem, 6)

    with pytest.raises(RuntimeError):
        mem.reflect(since=datetime.now(timezone.utc) - timedelta(days=30))

    assert mem.last_reflect_at is None  # not advanced
