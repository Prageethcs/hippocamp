"""LLM-driven memory consolidation.

`run_reflection()` reads recent episodes from a Memory, asks an LLM to
extract durable facts/preferences/reflections, and writes the output
back to the Memory. Near-duplicate facts are superseded via a
recall+similarity threshold. Memory's `last_reflect_at` is persisted on
success so subsequent runs only process new episodes.

Hippocamp does not pick an LLM — the caller supplies any object with a
`complete(prompt, *, system) -> str` method via `Memory(llm=...)`.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Iterable, Protocol

from pydantic import BaseModel, Field, ValidationError

if TYPE_CHECKING:
    from hippocamp.memory import Memory
    from hippocamp.types import RawRow


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------


class LLM(Protocol):
    """Minimal interface any LLM client must satisfy to power reflection.

    Adapters for Anthropic / OpenAI / Gemini / local models live outside
    Hippocamp; Hippocamp does not pick a model.
    """

    def complete(self, prompt: str, *, system: str | None = None) -> str: ...


class _Item(BaseModel):
    text: str
    evidence: list[str] = Field(default_factory=list)


class ReflectionDraft(BaseModel):
    """Schema the LLM must return — validated before any writes."""

    facts: list[_Item] = Field(default_factory=list)
    preferences: list[_Item] = Field(default_factory=list)
    reflections: list[_Item] = Field(default_factory=list)


class ReflectionReport(BaseModel):
    """Summary of a reflection run, returned to the caller."""

    new_facts: int = 0
    new_preferences: int = 0
    new_reflections: int = 0
    superseded: int = 0
    episodes_processed: int = 0
    notes: str = ""


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------


SYSTEM_PROMPT = """\
You are a memory distiller for a personal AI assistant. You receive a list
of conversation episodes (the user's interactions with various AI hosts)
and extract durable user-modelling content: stable facts, preferences, and
patterns.

OUTPUT a single JSON object with three keys:
  - facts:        list of stable facts about the user/project/world
  - preferences:  list of likes, dislikes, or working styles
  - reflections:  list of higher-order patterns spanning multiple episodes

Each item has the shape:
  {"text": "<the distilled statement>", "evidence": ["<episode_id>", ...]}

RULES:
- Extract only items GROUNDED in the episode content. Do not infer beyond
  what is stated in the episodes.
- Each item MUST list at least one episode id from the input as evidence.
- Phrase facts in third person about the user ("User works at X").
- Avoid one-shot specifics ("user asked about today's weather"); aim for
  stable patterns that would still be true next month.
- Skip items already covered by EXISTING_FACTS (provided below).
- Output ONLY the JSON object. No prose, no markdown fences, no commentary.
"""


# ---------------------------------------------------------------------------
# Lockfile
# ---------------------------------------------------------------------------


class _ReflectLock:
    """File lock at <store_dir>/.reflect.lock with a stale-after-1h policy."""

    STALE_AFTER = timedelta(hours=1)

    def __init__(self, store_dir: Path | None) -> None:
        self._path = (store_dir / ".reflect.lock") if store_dir else None

    def acquire(self) -> None:
        if self._path is None:
            return  # in-memory store: no lock needed
        if self._path.exists():
            mtime = datetime.fromtimestamp(
                self._path.stat().st_mtime, tz=timezone.utc
            )
            age = datetime.now(timezone.utc) - mtime
            if age < self.STALE_AFTER:
                raise RuntimeError(
                    f"reflect() locked by another process (lock at {self._path}, "
                    f"age {age}). Wait, or delete the lock if certain it's stale."
                )
        self._path.write_text(
            f"{os.getpid()} {datetime.now(timezone.utc).isoformat()}\n"
        )

    def release(self) -> None:
        if self._path is None:
            return
        try:
            self._path.unlink()
        except FileNotFoundError:
            pass


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def run_reflection(
    memory: "Memory",
    llm: LLM,
    *,
    since: str | datetime | None = None,
    max_episodes: int = 50,
    min_episodes: int = 5,
    dedup_threshold: float = 0.85,
    default_lookback: timedelta = timedelta(days=7),
) -> ReflectionReport:
    """Distil recent episodes into facts/preferences/reflections.

    Reads episodes since the resolved cutoff (`since` arg, else
    `memory.last_reflect_at`, else now - default_lookback), sends them to
    the LLM with the SYSTEM_PROMPT, validates the JSON output, and writes
    the surviving items back to the memory. Near-duplicate facts (recall
    similarity ≥ dedup_threshold) supersede the existing fact rather than
    creating a parallel one.

    Persists `last_reflect_at` only on a successful pass — if the LLM call
    or JSON parsing fails, the cutoff isn't advanced, so the next run
    retries the same window.
    """
    cutoff = _resolve_since(memory, since, default_lookback)

    lock = _ReflectLock(memory.store_dir)
    lock.acquire()
    try:
        episodes = memory._store.episodes_since(cutoff, limit=max_episodes)
        if len(episodes) < min_episodes:
            return ReflectionReport(
                episodes_processed=len(episodes),
                notes=(
                    f"Skipped: {len(episodes)} episodes since "
                    f"{cutoff.isoformat()} is below min_episodes={min_episodes}."
                ),
            )

        existing_facts = memory.recall(
            query="user identity preferences habits work",
            kinds=["fact", "preference"],
            limit=30,
        )

        prompt = (
            f"EPISODES:\n{_format_episodes(episodes)}\n\n"
            f"EXISTING_FACTS:\n{_format_existing_facts(existing_facts)}\n"
        )

        draft = _call_and_parse(llm, prompt, retries=1)

        valid_ids = {e.id for e in episodes}
        report = ReflectionReport(episodes_processed=len(episodes))

        for f in draft.facts:
            evidence = [eid for eid in f.evidence if eid in valid_ids]
            if not evidence:
                continue
            sup = _find_supersede_target(memory, f.text, "fact", dedup_threshold)
            memory.assert_fact(
                f.text,
                evidence=evidence,
                supersedes=[sup] if sup else None,
            )
            report.new_facts += 1
            if sup:
                report.superseded += 1

        for p in draft.preferences:
            evidence = [eid for eid in p.evidence if eid in valid_ids]
            if not evidence:
                continue
            # Preference's API doesn't yet support supersession; skip when
            # a near-duplicate already exists to avoid parallel preferences.
            if _find_supersede_target(memory, p.text, "preference", dedup_threshold):
                continue
            memory.assert_preference(p.text)
            report.new_preferences += 1

        for r in draft.reflections:
            sources = [eid for eid in r.evidence if eid in valid_ids]
            if not sources:
                continue
            memory.assert_reflection(r.text, sources=sources)
            report.new_reflections += 1

        memory.set_last_reflect_at(datetime.now(timezone.utc))
        return report
    finally:
        lock.release()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _resolve_since(
    memory: "Memory",
    since: str | datetime | None,
    default_lookback: timedelta,
) -> datetime:
    if isinstance(since, datetime):
        return since
    if isinstance(since, str):
        return datetime.fromisoformat(since)
    last = memory.last_reflect_at
    if last is not None:
        return last
    return datetime.now(timezone.utc) - default_lookback


def _format_episodes(episodes: Iterable["RawRow"]) -> str:
    lines = []
    for e in episodes:
        date = e.created_at.date().isoformat()
        snippet = e.text.replace("\n", " ")[:300]
        lines.append(f"[{e.id}] {date} {snippet}")
    return "\n".join(lines)


def _format_existing_facts(facts) -> str:
    if not facts:
        return "(none)"
    return "\n".join(f"- {f.text}" for f in facts[:30])


def _extract_json(text: str) -> str:
    """Find the first {...} block in `text` (defends against prose around JSON)."""
    m = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if not m:
        raise ValueError("no JSON object found in LLM output")
    return m.group(0)


def _call_and_parse(llm: LLM, prompt: str, *, retries: int = 1) -> ReflectionDraft:
    """Call LLM and parse its JSON output. Retry once on failure with a stricter nudge."""
    last_err: Exception | None = None
    current_prompt = prompt
    for attempt in range(retries + 1):
        raw = llm.complete(current_prompt, system=SYSTEM_PROMPT)
        try:
            blob = _extract_json(raw)
            data = json.loads(blob)
            return ReflectionDraft.model_validate(data)
        except (ValueError, json.JSONDecodeError, ValidationError) as e:
            last_err = e
            if attempt >= retries:
                raise RuntimeError(
                    f"LLM did not return valid JSON after {retries + 1} attempts: {last_err}"
                ) from last_err
            current_prompt = current_prompt + (
                "\n\n[The previous response was not valid JSON. Output ONLY a "
                "single JSON object matching the schema; no prose, no fences.]"
            )
    raise RuntimeError("unreachable")  # pragma: no cover


def _find_supersede_target(
    memory: "Memory",
    text: str,
    kind: str,
    threshold: float,
) -> str | None:
    """Recall the most-similar existing memory of `kind`. Return its id if sim >= threshold."""
    hits = memory.recall(query=text, kinds=[kind], limit=3)
    if not hits:
        return None
    top = hits[0]
    if top.why.similarity >= threshold:
        return top.id
    return None
