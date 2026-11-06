from __future__ import annotations

import hashlib
import re

from .cache import ResilientCache
from .contracts import PolicyChunk
from .providers import ModelProvider
from .repository import Repository


class RetrievalService:
    def __init__(
        self,
        repository: Repository,
        provider: ModelProvider,
        cache: ResilientCache,
        cache_ttl_seconds: int,
        policy_index_version: str = "policies-2026-01",
    ) -> None:
        self.repository = repository
        self.provider = provider
        self.cache = cache
        self.cache_ttl_seconds = cache_ttl_seconds
        self.policy_index_version = policy_index_version

#Pakai Hybrid Search (Lexical + Semantic) untuk pencarian kebijakan.
    def search(self, query: str, top_k: int = 3) -> list[PolicyChunk]:
        normalized = " ".join(query.casefold().split())
        if not normalized or top_k < 1:
            return []
        key_digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
        cache_key = f"retrieval:{self.policy_index_version}:{top_k}:{key_digest}"
        cached = self.cache.get(cache_key)
        if isinstance(cached, list):
            try:
                return [PolicyChunk.model_validate(item) for item in cached[:top_k]]
            except (TypeError, ValueError):
                pass

        lexical = self.repository.lexical_search(normalized, max(top_k * 3, 5))
        semantic: list[PolicyChunk] = []
        try:
            embeddings = self.provider.embed([normalized])
            if embeddings:
                semantic = self.repository.vector_search(embeddings[0], max(top_k * 3, 5))
        except (RuntimeError, TimeoutError, ValueError, OSError):
            semantic = []

        candidates: dict[str, PolicyChunk] = {}
        scores: dict[str, float] = {}
        for rank, chunk in enumerate(lexical, start=1):
            candidates[chunk.chunk_id] = chunk
            scores[chunk.chunk_id] = scores.get(chunk.chunk_id, 0.0) + 1.0 / (60 + rank)
        for rank, chunk in enumerate(semantic, start=1):
            candidates[chunk.chunk_id] = chunk
            scores[chunk.chunk_id] = scores.get(chunk.chunk_id, 0.0) + 1.0 / (60 + rank)

        terms = set(re.findall(r"\w+", normalized))

        def rank_key(chunk: PolicyChunk) -> tuple[float, int, str]:
            content_terms = set(
                re.findall(
                    r"\w+",
                    f"{chunk.title} {chunk.section} {chunk.content}".casefold(),
                )
            )
            keyword_score = len(terms & content_terms)
            return (-scores[chunk.chunk_id], -keyword_score, chunk.chunk_id)

        results = sorted(candidates.values(), key=rank_key)[:top_k]
        self.cache.set(
            cache_key,
            [chunk.model_dump(mode="json") for chunk in results],
            self.cache_ttl_seconds,
        )
        return results
