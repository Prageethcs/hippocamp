"""Semantic recall test using the fastembed (ONNX) BGE-small embedder.

Skipped automatically when fastembed isn't installed. When it is, this test
proves that the lightweight fastembed path gives the same kind of semantic
recall as the sentence-transformers path covered in test_semantic.py.
"""

from __future__ import annotations

import pytest

from hippocamp import Memory


def _has_fastembed() -> bool:
    try:
        import fastembed  # noqa: F401
        return True
    except ImportError:
        return False


pytestmark = pytest.mark.skipif(
    not _has_fastembed(),
    reason="fastembed not installed",
)


@pytest.fixture(scope="module")
def fastembed_embedder():
    from hippocamp.embedders import FastembedBgeEmbedder
    return FastembedBgeEmbedder()


def test_fastembed_recall_finds_paraphrase(fastembed_embedder):
    mem = Memory(path=":memory:", embedder=fastembed_embedder)

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


def test_fastembed_vector_shape(fastembed_embedder):
    """fastembed BGE-small must return 384-dim vectors of the right type."""
    vec = fastembed_embedder("hello world")
    assert isinstance(vec, list)
    assert len(vec) == 384
    assert all(isinstance(x, float) for x in vec[:5])
