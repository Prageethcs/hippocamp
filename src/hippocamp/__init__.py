"""Hippocamp — local-first agent memory."""

from importlib.metadata import version

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

__version__ = version("hippocamp")

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
