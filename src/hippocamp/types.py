"""Public types for Hippocamp."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

Kind = Literal["episode", "fact", "preference", "reflection"]


class Why(BaseModel):
    """Trace of why a memory was retrieved and how its score was composed."""

    similarity: float
    recency: float
    kind_boost: float
    salience: float
    total: float
    note: str = ""


class RecallResult(BaseModel):
    id: str
    kind: Kind
    text: str
    score: float
    why: Why
    created_at: datetime
    metadata: dict[str, Any] = Field(default_factory=dict)


class RawRow(BaseModel):
    id: str
    kind: Kind
    text: str
    created_at: datetime
    last_seen_at: datetime
    salience: float
    metadata: dict[str, Any]
    embedding: list[float]


class Inventory(BaseModel):
    episodes: int = 0
    facts: int = 0
    preferences: int = 0
    reflections: int = 0
    bytes_on_disk: int = 0
    last_reflect: datetime | None = None


class CompactReport(BaseModel):
    merged: int = 0
    dropped: int = 0


class Episode(BaseModel):
    id: str
    text: str
    actors: list[str] = Field(default_factory=list)
    created_at: datetime


class Fact(BaseModel):
    id: str
    text: str
    evidence: list[str] = Field(default_factory=list)
    superseded_at: datetime | None = None
    created_at: datetime


class Preference(BaseModel):
    id: str
    text: str
    strength: float = 1.0
    created_at: datetime


class Reflection(BaseModel):
    id: str
    text: str
    sources: list[str] = Field(default_factory=list)
    created_at: datetime
