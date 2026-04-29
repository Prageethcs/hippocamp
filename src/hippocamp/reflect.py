"""LLM-driven consolidation pass.

v0.0.1: stub. v0.1.0 will cluster recent episodes, extract candidate facts
via an LLM, detect contradictions with existing facts, and mark redundant
memories for collapse. The public `run_reflection` signature is fixed.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class ReflectionReport(BaseModel):
    new_facts: list[str] = Field(default_factory=list)
    new_reflections: list[str] = Field(default_factory=list)
    superseded: list[str] = Field(default_factory=list)
    notes: str = ""


def run_reflection(
    store,
    llm,
    *,
    since: str | datetime | None = None,
) -> ReflectionReport:
    raise NotImplementedError("reflect() lands in v0.1.0")
