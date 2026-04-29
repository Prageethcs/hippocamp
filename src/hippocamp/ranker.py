"""Four-signal ranker: similarity + recency + kind-boost + salience.

Each ranked result carries a `Why` trace that explains how its score was
composed. Surfacing the *why* is one of Hippocamp's wedges over single-
bucket vector stores.
"""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any, Iterable

from hippocamp.types import RawRow, RecallResult, Why

W_SIM = 1.0
W_REC = 0.3
W_KIND = 0.2
W_SAL = 0.4

KIND_BOOSTS: dict[str, float] = {
    "preference": 1.2,
    "fact": 1.1,
    "reflection": 1.05,
    "episode": 1.0,
}

RECENCY_HALFLIFE_DAYS = 30.0


def rank(
    rows: Iterable[RawRow],
    *,
    query_emb: list[float],
    context: dict[str, Any] | None,
    now: datetime,
) -> list[RecallResult]:
    results: list[RecallResult] = []
    for row in rows:
        sim = _cosine(query_emb, row.embedding)
        rec = _recency_decay(row.created_at, now)
        kb = KIND_BOOSTS.get(row.kind, 1.0)
        sal = _salience_factor(row.salience)

        total = W_SIM * sim + W_REC * rec + W_KIND * (kb - 1.0) + W_SAL * sal

        why = Why(
            similarity=sim,
            recency=rec,
            kind_boost=kb,
            salience=sal,
            total=total,
            note=_compose_note(sim, rec, kb, sal),
        )

        results.append(
            RecallResult(
                id=row.id,
                kind=row.kind,
                text=row.text,
                score=total,
                why=why,
                created_at=row.created_at,
                metadata=row.metadata,
            )
        )

    results.sort(key=lambda r: r.score, reverse=True)
    return results


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b:
        return 0.0
    n = min(len(a), len(b))
    dot = sum(a[i] * b[i] for i in range(n))
    na = math.sqrt(sum(x * x for x in a[:n])) or 1e-9
    nb = math.sqrt(sum(x * x for x in b[:n])) or 1e-9
    return dot / (na * nb)


def _recency_decay(created_at: datetime, now: datetime) -> float:
    age_days = max(0.0, (now - created_at).total_seconds() / 86400.0)
    return 0.5 ** (age_days / RECENCY_HALFLIFE_DAYS)


def _salience_factor(salience: float) -> float:
    return math.log1p(max(0.0, salience))


def _compose_note(sim: float, rec: float, kb: float, sal: float) -> str:
    parts = [f"sim={sim:.2f}"]
    if rec < 0.95:
        parts.append(f"recency×{rec:.2f}")
    if kb != 1.0:
        parts.append(f"kind×{kb:.2f}")
    if sal > 0:
        parts.append(f"salience×{1 + sal:.2f}")
    return ", ".join(parts)
