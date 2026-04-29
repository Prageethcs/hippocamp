"""Embedders turn text into fixed-size float vectors.

`HashEmbedder` is a deterministic stub for tests and CI.
`BgeSmallEmbedder` runs a real local sentence-transformers model.
`default_embedder()` picks the best available — real model if installed,
else the stub with a warning.
"""

from __future__ import annotations

import hashlib
import warnings
from typing import Protocol


class Embedder(Protocol):
    name: str
    dim: int

    def __call__(self, text: str) -> list[float]: ...


class HashEmbedder:
    """Deterministic sha256 → 32-dim float vector.

    Not semantically meaningful. Use only for tests and CI.
    """

    name = "hash-32"
    dim = 32

    def __call__(self, text: str) -> list[float]:
        h = hashlib.sha256(text.encode("utf-8")).digest()
        return [(b - 128) / 128.0 for b in h]


class BgeSmallEmbedder:
    """Local sentence-transformers embedder (BAAI/bge-small-en-v1.5).

    Produces 384-dim normalized vectors. First call downloads the model
    (~130MB) to the HuggingFace cache. Runs on CPU by default.
    """

    name = "bge-small-en-v1.5"
    dim = 384

    def __init__(self, model_id: str = "BAAI/bge-small-en-v1.5") -> None:
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as e:
            raise ImportError(
                "BgeSmallEmbedder requires sentence-transformers. "
                "Install with: pip install 'hippocamp[embeddings]'"
            ) from e
        self._model = SentenceTransformer(model_id)

    def __call__(self, text: str) -> list[float]:
        vec = self._model.encode(text, normalize_embeddings=True)
        return vec.tolist()


def default_embedder() -> Embedder:
    """Return the best available embedder, with a warning if falling back."""
    try:
        return BgeSmallEmbedder()
    except ImportError:
        warnings.warn(
            "Falling back to HashEmbedder — recall will not be semantic. "
            "Install 'hippocamp[embeddings]' for real embeddings.",
            UserWarning,
            stacklevel=2,
        )
        return HashEmbedder()
