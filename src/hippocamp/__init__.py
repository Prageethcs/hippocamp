"""Hippocamp — local-first agent memory."""

from hippocamp.memory import Memory
from hippocamp.types import (
    CompactReport,
    Episode,
    Fact,
    Inventory,
    Preference,
    RecallResult,
    Reflection,
    Why,
)

__version__ = "0.3.3"

__all__ = [
    "Memory",
    "Episode",
    "Fact",
    "Preference",
    "Reflection",
    "RecallResult",
    "Inventory",
    "CompactReport",
    "Why",
]
