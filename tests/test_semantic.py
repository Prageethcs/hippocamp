"""Semantic recall test using the real BGE small embedder.

Skipped automatically when sentence-transformers isn't installed, so
the fast suite stays fast. When the optional dep is present, this test
proves that recall is genuinely semantic (not just round-tripping).
"""

from __future__ import annotations

import pytest

from hippocamp import Memory


def _has_sentence_transformers() -> bool:
    try:
        import sentence_transformers  # noqa: F401
        return True
    except ImportError:
        return False


pytestmark = pytest.mark.skipif(
    not _has_sentence_transformers(),
    reason="sentence-transformers not installed",
)


@pytest.fixture(scope="module")
def real_embedder():
    from hippocamp.embedders import BgeSmallEmbedder
    return BgeSmallEmbedder()


def test_semantic_recall_finds_paraphrase(real_embedder):
    mem = Memory(path=":memory:", embedder=real_embedder)

    gcp_id = mem.observe(
        "user wants to deploy a Python service to Google Cloud Platform"
    )
    mem.observe("user is shopping for new running shoes")
    mem.observe("user enjoys cooking pasta on Sunday evenings")

    hits = mem.recall("how do I push my code to GCP?", limit=3)

    assert hits, "expected results"
    assert hits[0].id == gcp_id, (
        f"expected GCP episode on top, got: {hits[0].text!r}"
    )
    assert hits[0].why.similarity > 0.5, (
        f"expected strong semantic similarity, got {hits[0].why.similarity:.2f}"
    )


def test_unrelated_query_ranks_unrelated_episode_lower(real_embedder):
    mem = Memory(path=":memory:", embedder=real_embedder)

    mem.observe("project uses Python 3.13 and FastAPI")
    cooking_id = mem.observe("user enjoys cooking pasta on Sunday evenings")

    hits = mem.recall("what's a good carbonara recipe?", limit=2)

    assert hits[0].id == cooking_id
    assert hits[0].why.similarity > hits[1].why.similarity
