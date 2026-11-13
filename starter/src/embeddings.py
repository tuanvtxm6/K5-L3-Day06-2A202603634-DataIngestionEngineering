"""OpenAI embedding adapter (text-embedding-3-small by default).

Documents and queries are embedded the same way (no instruction prefix), as
the OpenAI embedding models expect. There is no fallback: a missing key or an
API error raises, so mock/random vectors can never end up in the store.
"""
from __future__ import annotations

import math
import os
import time
from typing import Protocol

from openai import OpenAI


class Embedder(Protocol):
    model_name: str
    dimensions: int

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Return one vector per input text, in the same order."""
        ...

    def embed_query(self, question: str) -> list[float]:
        """Return a query vector compatible with the stored document vectors."""
        ...


# Default output sizes of OpenAI embedding models.
KNOWN_DIMENSIONS = {
    "text-embedding-3-small": 1536,
    "text-embedding-3-large": 3072,
    "text-embedding-ada-002": 1536,
}
# USD per 1M input tokens, list price when this code was written (2026-11);
# check https://developers.openai.com/api/docs/models before reporting cost.
PRICE_PER_MTOK = {
    "text-embedding-3-small": 0.02,
    "text-embedding-3-large": 0.13,
    "text-embedding-ada-002": 0.10,
}


class OpenAIEmbedder:
    """Batching OpenAI embedder that also counts tokens for cost reporting."""

    def __init__(self, model_name: str, batch_size: int = 128, api_key: str | None = None) -> None:
        if not model_name:
            raise ValueError("EMBEDDING_MODEL is empty: set it in starter/.env")
        key = api_key or os.getenv("OPENAI_API_KEY")
        if not key:
            raise RuntimeError("OPENAI_API_KEY missing: set it in starter/.env (never commit it)")
        self.model_name = model_name
        self.batch_size = batch_size
        self.client = OpenAI(api_key=key, max_retries=5, timeout=60)
        self.prompt_tokens = 0
        self.requests = 0
        self.seconds = 0.0
        self.dimensions = KNOWN_DIMENSIONS.get(model_name) or len(self._embed(["dimension probe"])[0])

    def _embed(self, texts: list[str]) -> list[list[float]]:
        if any(not t.strip() for t in texts):
            raise ValueError("cannot embed empty text")
        start = time.perf_counter()
        response = self.client.embeddings.create(model=self.model_name, input=texts)
        self.seconds += time.perf_counter() - start
        self.requests += 1
        self.prompt_tokens += response.usage.prompt_tokens
        vectors = [item.embedding for item in sorted(response.data, key=lambda d: d.index)]
        if len(vectors) != len(texts):
            raise RuntimeError(f"provider returned {len(vectors)} vectors for {len(texts)} inputs")
        for vector in vectors:
            if hasattr(self, "dimensions") and len(vector) != self.dimensions:
                raise RuntimeError(f"expected {self.dimensions} dims, got {len(vector)}")
            if not all(math.isfinite(x) for x in vector):
                raise RuntimeError("provider returned a non-finite vector")
        return vectors

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for i in range(0, len(texts), self.batch_size):
            vectors.extend(self._embed(texts[i:i + self.batch_size]))
        return vectors

    def embed_query(self, question: str) -> list[float]:
        return self._embed([question])[0]

    def cost_usd(self) -> float | None:
        price = PRICE_PER_MTOK.get(self.model_name)
        return None if price is None else self.prompt_tokens / 1_000_000 * price

    def usage(self) -> dict:
        return {"model": self.model_name, "dimensions": self.dimensions,
                "prompt_tokens": self.prompt_tokens, "requests": self.requests,
                "api_seconds": round(self.seconds, 2), "cost_usd": self.cost_usd(),
                "price_per_mtok_usd": PRICE_PER_MTOK.get(self.model_name)}
