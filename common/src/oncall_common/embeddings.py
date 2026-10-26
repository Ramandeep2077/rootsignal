"""Text embeddings for alert grouping and runbook search.

- ``LocalEmbedder``: sentence-transformers/all-MiniLM-L6-v2 run locally through fastembed (ONNX Runtime, CPU).
  No PyTorch, no API key, ~90 MB model download on first use.
- ``HashEmbedder``: deterministic feature hashing of word unigrams/bigrams. No model download; used in tests
  and CI. Still lexically meaningful, so similarity-based logic can be tested realistically.
"""

from __future__ import annotations

import hashlib
import itertools
import os
import re
from collections.abc import Sequence
from functools import lru_cache
from pathlib import Path
from typing import Protocol

import numpy as np

from oncall_common.db import EMBEDDING_DIM
from oncall_common.settings import common_settings

_TOKEN = re.compile(r"[a-z][a-z0-9_.-]+")


class Embedder(Protocol):
    model_name: str

    def embed(self, texts: Sequence[str]) -> np.ndarray:
        """Return an (n, EMBEDDING_DIM) array of L2-normalised vectors."""
        ...


def _normalise(vectors: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return (vectors / norms).astype(np.float32)


class HashEmbedder:
    model_name = "hash-384"

    def __init__(self, dim: int = EMBEDDING_DIM) -> None:
        self.dim = dim

    def _bucket(self, feature: str) -> tuple[int, float]:
        digest = hashlib.blake2b(feature.encode(), digest_size=8).digest()
        value = int.from_bytes(digest, "little")
        return value % self.dim, 1.0 if (value >> 63) & 1 else -1.0

    def embed(self, texts: Sequence[str]) -> np.ndarray:
        out = np.zeros((len(texts), self.dim), dtype=np.float32)
        for row, text in enumerate(texts):
            tokens = [t for t in _TOKEN.findall(text.lower()) if not t.isdigit()]
            features = tokens + [f"{a} {b}" for a, b in itertools.pairwise(tokens)]
            for feature in features:
                index, sign = self._bucket(feature)
                out[row, index] += sign
        return _normalise(out)


class LocalEmbedder:
    def __init__(self, model_name: str) -> None:
        from fastembed import TextEmbedding  # imported lazily: optional dependency

        self.model_name = model_name
        cache_dir = os.environ.get("FASTEMBED_CACHE_PATH", str(Path.home() / ".cache" / "fastembed"))
        self._model = TextEmbedding(model_name=model_name, cache_dir=cache_dir)

    def embed(self, texts: Sequence[str]) -> np.ndarray:
        vectors = np.array(list(self._model.embed(list(texts))), dtype=np.float32)
        return _normalise(vectors)


@lru_cache(maxsize=4)
def get_embedder(provider: str | None = None, model: str | None = None) -> Embedder:
    settings = common_settings()
    provider = (provider or settings.embeddings_provider).lower()
    if provider == "hash":
        return HashEmbedder()
    if provider == "local":
        return LocalEmbedder(model or settings.embeddings_model)
    raise ValueError(f"Unknown EMBEDDINGS_PROVIDER '{provider}' (expected 'local' or 'hash')")


def cosine(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(a, b))
