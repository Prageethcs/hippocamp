"""Embedders turn text into fixed-size float vectors.

`HashEmbedder` is a deterministic stub for tests and CI.
`FastembedBgeEmbedder` runs BGE-small via fastembed (ONNX Runtime) —
the lightweight default, ~150MB install footprint.
`BgeSmallEmbedder` runs the same BGE-small weights via
sentence-transformers / PyTorch — kept for compatibility (~900MB
install).
`Qwen3Embedder` runs a larger, higher-quality local model via
sentence-transformers.
`default_embedder()` picks the best available — Qwen3 if installed,
else fastembed-BGE, else sentence-transformers-BGE, else the stub
with a warning.
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


class FastembedBgeEmbedder:
    """ONNX-Runtime BGE-small-en-v1.5 via fastembed.

    Numerically equivalent to BgeSmallEmbedder (same BAAI weights), but
    avoids pulling in PyTorch / transformers / sklearn. Install footprint
    is ~150MB instead of ~900MB. First call downloads the ONNX model
    (~130MB) to fastembed's cache. Vectors come back L2-normalized.
    """

    name = "bge-small-en-v1.5"
    dim = 384

    def __init__(self, model_id: str = "BAAI/bge-small-en-v1.5") -> None:
        try:
            from fastembed import TextEmbedding
        except ImportError as e:
            raise ImportError(
                "FastembedBgeEmbedder requires fastembed. "
                "Install with: pip install 'hippocamp[embeddings-lite]'"
            ) from e
        self._model = TextEmbedding(model_name=model_id)

    def __call__(self, text: str) -> list[float]:
        vec = next(self._model.embed([text]))
        return vec.tolist()


class BgeSmallEmbedder:
    """Local sentence-transformers embedder (BAAI/bge-small-en-v1.5).

    Produces 384-dim normalized vectors. First call downloads the model
    (~130MB) to the HuggingFace cache. Runs on CPU by default. Same
    weights and output as FastembedBgeEmbedder; only kept for users who
    already have sentence-transformers installed (e.g. for Qwen3) and
    want a single backend.
    """

    name = "bge-small-en-v1.5"
    dim = 384

    def __init__(self, model_id: str = "BAAI/bge-small-en-v1.5") -> None:
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as e:
            raise ImportError(
                "BgeSmallEmbedder requires sentence-transformers. "
                "Install with: pip install 'hippocamp[embeddings]'. "
                "For a lighter install, use FastembedBgeEmbedder via "
                "pip install 'hippocamp[embeddings-lite]'."
            ) from e
        self._model = SentenceTransformer(model_id)

    def __call__(self, text: str) -> list[float]:
        vec = self._model.encode(text, normalize_embeddings=True)
        return vec.tolist()


class Qwen3Embedder:
    """Local sentence-transformers embedder (Qwen/Qwen3-Embedding-0.6B).

    Produces 1024-dim normalized vectors. First call downloads the model
    (~1.2GB) to the HuggingFace cache. Higher recall quality than BGE-small
    on harder retrieval cases (vocabulary mismatch, inferential matching).
    """

    name = "Qwen3-Embedding-0.6B"
    dim = 1024

    def __init__(self, model_id: str = "Qwen/Qwen3-Embedding-0.6B") -> None:
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as e:
            raise ImportError(
                "Qwen3Embedder requires sentence-transformers. "
                "Install with: pip install 'hippocamp[embeddings]'"
            ) from e
        self._model = SentenceTransformer(model_id)

    def __call__(self, text: str) -> list[float]:
        vec = self._model.encode(text, normalize_embeddings=True)
        return vec.tolist()


def default_embedder() -> Embedder:
    """Return the best available embedder, with a warning if falling back.

    Order: Qwen3 (best recall, needs sentence-transformers) → fastembed-BGE
    (light + fast) → sentence-transformers-BGE → hash stub.
    """
    try:
        return Qwen3Embedder()
    except ImportError:
        pass
    try:
        return FastembedBgeEmbedder()
    except ImportError:
        pass
    try:
        return BgeSmallEmbedder()
    except ImportError:
        warnings.warn(
            "Falling back to HashEmbedder — recall will not be semantic. "
            "Install 'hippocamp[embeddings-lite]' for real embeddings "
            "(or '[embeddings]' for the heavier sentence-transformers stack).",
            UserWarning,
            stacklevel=2,
        )
        return HashEmbedder()
