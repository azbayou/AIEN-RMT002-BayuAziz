from __future__ import annotations

from datetime import date
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
    def search(self, query: str, top_k: int = 3, as_of: date | None = None) -> list[PolicyChunk]:
        normalized = " ".join(query.casefold().split())
        if not normalized or top_k < 1:
            return []
        effective_as_of = as_of or date.today()
        key_digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
        if hasattr(self.repository, "policy_fingerprint"):
            try:
                fp = self.repository.policy_fingerprint(as_of=effective_as_of)
            except TypeError:
                fp = self.repository.policy_fingerprint()
        else:
            fp = "static"
        cache_key = f"retrieval:{self.policy_index_version}:{effective_as_of.isoformat()}:{fp}:{top_k}:{key_digest}"
        cached = self.cache.get(cache_key)
        if isinstance(cached, list):
            try:
                return [PolicyChunk.model_validate(item) for item in cached[:top_k]]
            except (TypeError, ValueError):
                pass

        try:
            lexical = self.repository.lexical_search(normalized, max(top_k * 3, 5), as_of=effective_as_of)
        except TypeError:
            lexical = self.repository.lexical_search(normalized, max(top_k * 3, 5))
        semantic: list[PolicyChunk] = []
        embedding_degraded = False
        try:
            embeddings = self.provider.embed([normalized])
            if embeddings and embeddings[0]:
                try:
                    semantic = self.repository.vector_search(embeddings[0], max(top_k * 3, 5), as_of=effective_as_of)
                except TypeError:
                    semantic = self.repository.vector_search(embeddings[0], max(top_k * 3, 5))
            else:
                embedding_degraded = True
        except Exception:
            semantic = []
            embedding_degraded = True

        candidates: dict[str, PolicyChunk] = {}
        rrf_scores: dict[str, float] = {}
        for rank, chunk in enumerate(lexical, start=1):
            candidates[chunk.chunk_id] = chunk
            rrf_scores[chunk.chunk_id] = rrf_scores.get(chunk.chunk_id, 0.0) + 1.0 / (60 + rank)
        for rank, chunk in enumerate(semantic, start=1):
            candidates[chunk.chunk_id] = chunk
            rrf_scores[chunk.chunk_id] = rrf_scores.get(chunk.chunk_id, 0.0) + 1.0 / (60 + rank)

        stopwords = {"berapa", "apakah", "bagaimana", "kapan", "siapa", "yang", "dan", "di", "ke", "dari", "untuk", "pada", "saya", "aku", "bisa", "boleh", "per"}
        raw_terms = set(re.findall(r"\w+", normalized))
        terms = (raw_terms - stopwords) or raw_terms

        combined_scores: dict[str, float] = {}
        keyword_hits: dict[str, int] = {}
        for chunk_id, chunk in candidates.items():
            title_terms = set(
                re.findall(
                    r"\w+",
                    f"{chunk.title} {chunk.section}".casefold(),
                )
            )
            content_terms = set(
                re.findall(
                    r"\w+",
                    f"{chunk.title} {chunk.section} {chunk.content}".casefold(),
                )
            )
            overlap = len(terms & content_terms) + len(terms & title_terms)
            keyword_hits[chunk_id] = overlap
            # Gabungkan RRF score dengan bobot keyword tie-breaker (0.0002 per kata kunci yang cocok)
            combined_scores[chunk_id] = rrf_scores[chunk_id] + (0.0002 * overlap)

        def rank_key(chunk: PolicyChunk) -> tuple[float, int, str]:
            return (-combined_scores[chunk.chunk_id], -keyword_hits[chunk.chunk_id], chunk.chunk_id)

        ranked_chunks = sorted(candidates.values(), key=rank_key)[:top_k]
        results = [
            chunk.model_copy(update={"score": round(combined_scores[chunk.chunk_id], 6)})
            for chunk in ranked_chunks
        ]
        if not embedding_degraded:
            self.cache.set(
                cache_key,
                [chunk.model_dump(mode="json") for chunk in results],
                self.cache_ttl_seconds,
            )
        return results
