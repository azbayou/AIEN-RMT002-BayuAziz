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

    _SYNONYM_MAP: dict[str, str] = {
        "jatah": "hak dan saldo cuti pegawai tetap",
        "wfh": "kerja jarak jauh",
        "remote": "kerja jarak jauh",
        "probation": "masa percobaan kelayakan cuti",
        "surat": "cuti sakit pemberitahuan dokumen pendukung",
        "dokter": "cuti sakit pemberitahuan dokumen pendukung",
        "carryover": "sisa cuti dibawa tahun berikutnya",
        "dibawa": "sisa cuti dibawa tahun berikutnya",
        "approval": "persetujuan cuti eskalasi manajer",
    }

    @classmethod
    def _expand_query(cls, normalized: str) -> str:
        tokens = set(re.findall(r"[a-z0-9]+", normalized))
        expansions = [phrase for key, phrase in cls._SYNONYM_MAP.items() if key in tokens]
        if not expansions:
            return normalized
        return f"{normalized} {' '.join(expansions)}"

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

        expanded_query = self._expand_query(normalized)
        lexical = self.repository.lexical_search(expanded_query, max(top_k * 3, 5))
        semantic: list[PolicyChunk] = []
        embedding_degraded = False
        try:
            embeddings = self.provider.embed([expanded_query])
            if embeddings:
                semantic = self.repository.vector_search(embeddings[0], max(top_k * 3, 5))
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
        raw_terms = set(re.findall(r"\w+", expanded_query))
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
            # Gabungkan RRF score dengan bobot keyword reranking (0.01 per kata kunci yang cocok)
            combined_scores[chunk_id] = rrf_scores[chunk_id] + (0.01 * overlap)

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
