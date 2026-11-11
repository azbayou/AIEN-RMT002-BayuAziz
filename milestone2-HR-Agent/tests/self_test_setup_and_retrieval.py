from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import MagicMock
import pytest

from src.cache import NullCache, ResilientCache
from src.contracts import PolicyChunk
from src.providers import DeterministicProvider
from src.repository import MemoryRepository
from src.retrieval import RetrievalService
from src.setup_lab import ROOT, chunk_policy


# ==============================================================================
# WBS-07: Policy Chunking & Setup Lab Verification
# ==============================================================================


def test_chunk_policy_validates_front_matter() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)

        # Missing front matter
        f1 = tmp_path / "f1.md"
        f1.write_text("Just regular text", encoding="utf-8")
        with pytest.raises(ValueError, match="missing front matter"):
            chunk_policy(f1)

        # Incomplete front matter (unclosed ---)
        f2 = tmp_path / "f2.md"
        f2.write_text("---\ndocument_id: TEST\nversion: 1\n", encoding="utf-8")
        with pytest.raises(ValueError, match="incomplete front matter"):
            chunk_policy(f2)

        # Missing required metadata
        f3 = tmp_path / "f3.md"
        f3.write_text("---\ndocument_id: TEST\n---\n## Section\nContent", encoding="utf-8")
        with pytest.raises(ValueError, match="missing required metadata"):
            chunk_policy(f3)

        # No non-empty sections
        f4 = tmp_path / "f4.md"
        f4.write_text(
            "---\ndocument_id: TEST\ntitle: T\nversion: 1\neffective_date: 2026-01-01\n---\n",
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="no non-empty sections"):
            chunk_policy(f4)


def test_chunk_policy_all_repo_policies_are_valid() -> None:
    policy_files = list((ROOT / "data" / "policies").glob("*.md"))
    assert len(policy_files) >= 7

    for path in policy_files:
        chunks = chunk_policy(path)
        assert len(chunks) >= 1
        for chunk in chunks:
            assert chunk["chunk_id"].startswith(chunk["document_id"])
            assert chunk["document_id"]
            assert chunk["title"]
            assert chunk["section"]
            assert chunk["version"]
            assert chunk["effective_date"]
            assert len(chunk["content"]) > 10


# ==============================================================================
# WBS-08: Retrieval Service Verification
# ==============================================================================


def _make_sample_chunks() -> list[PolicyChunk]:
    return [
        PolicyChunk(
            chunk_id="HR-LEAVE-001:c1",
            document_id="HR-LEAVE-001",
            title="Kebijakan Cuti Tahunan",
            section="Ketentuan Umum",
            version="1.0",
            effective_date="2026-01-01",
            content="Karyawan berhak atas jatah cuti tahunan sebanyak 12 hari kerja per tahun.",
        ),
        PolicyChunk(
            chunk_id="HR-SICK-002:c1",
            document_id="HR-SICK-002",
            title="Kebijakan Cuti Sakit",
            section="Ketentuan Sakit",
            version="1.0",
            effective_date="2026-01-01",
            content="Cuti sakit dapat diambil dengan surat keterangan dokter bila lebih dari dua hari.",
        ),
    ]


def test_retrieval_empty_query_or_zero_top_k() -> None:
    repo = MemoryRepository()
    service = RetrievalService(repo, DeterministicProvider(), NullCache(), 300)

    assert service.search("", top_k=3) == []
    assert service.search("    ", top_k=3) == []
    assert service.search("cuti", top_k=0) == []
    assert service.search("cuti", top_k=-1) == []


def test_retrieval_cache_hit_and_version_isolation() -> None:
    repo = MemoryRepository()
    repo.chunks = _make_sample_chunks()

    mock_cache = MagicMock()
    mock_cache.get.return_value = None

    service_v1 = RetrievalService(
        repo,
        DeterministicProvider(),
        mock_cache,
        300,
        policy_index_version="v1",
    )
    results = service_v1.search("cuti tahunan", top_k=2)
    assert len(results) >= 1

    # Verify cache key format
    set_call = mock_cache.set.call_args
    assert set_call is not None
    cache_key = set_call[0][0]
    assert cache_key.startswith("retrieval:v1:2:")

    # When cache hits
    mock_cache.get.return_value = [chunk.model_dump(mode="json") for chunk in results]
    hit_results = service_v1.search("cuti tahunan", top_k=2)
    assert len(hit_results) == len(results)
    assert hit_results[0].chunk_id == results[0].chunk_id


def test_retrieval_corrupt_cache_degrades_to_fresh_search() -> None:
    repo = MemoryRepository()
    repo.chunks = _make_sample_chunks()

    mock_cache = MagicMock()
    # Cache returns invalid data structure
    mock_cache.get.return_value = [{"corrupted": "structure"}]

    service = RetrievalService(repo, DeterministicProvider(), mock_cache, 300)
    results = service.search("cuti tahunan", top_k=2)

    # Should fall through to repository search
    assert len(results) >= 1
    assert results[0].document_id == "HR-LEAVE-001"


def test_retrieval_embedding_failure_degrades_to_lexical() -> None:
    repo = MemoryRepository()
    repo.chunks = _make_sample_chunks()

    class BrokenEmbeddingProvider(DeterministicProvider):
        def embed(self, texts):
            raise TimeoutError("Embedding provider unreachable")

    service = RetrievalService(repo, BrokenEmbeddingProvider(), NullCache(), 300)
    results = service.search("cuti tahunan", top_k=2)

    # Lexical search still successfully finds the policy chunk
    assert len(results) >= 1
    assert results[0].document_id == "HR-LEAVE-001"


# ==============================================================================
# WBS-22: Hybrid RAG, Keyword Reranking & Degraded Cache Safety
# ==============================================================================


def test_retrieval_does_not_cache_when_embedding_provider_fails() -> None:
    repo = MemoryRepository()
    repo.chunks = _make_sample_chunks()

    class BrokenEmbeddingProvider(DeterministicProvider):
        def embed(self, texts):
            raise TimeoutError("Embedding provider unreachable")

    mock_cache = MagicMock()
    mock_cache.get.return_value = None

    service = RetrievalService(repo, BrokenEmbeddingProvider(), mock_cache, 300)
    results = service.search("cuti tahunan", top_k=2)

    assert len(results) >= 1
    mock_cache.set.assert_not_called()


def test_keyword_reranking_promotes_exact_term_match() -> None:
    chunk_a = PolicyChunk(
        chunk_id="P-01:c1",
        document_id="P-01",
        title="Kebijakan Umum Operasional",
        section="Ketentuan Umum",
        version="1.0",
        effective_date="2026-01-01",
        content="Informasi regulasi umum dan operasional kantor harian.",
    )
    chunk_b = PolicyChunk(
        chunk_id="P-02:c1",
        document_id="P-02",
        title="Kebijakan Reimbursement",
        section="Klaim Kacamata",
        version="1.0",
        effective_date="2026-01-01",
        content="Penggantian biaya klaim kacamata untuk pegawai tetap.",
    )
    repo = MemoryRepository()
    repo.chunks = [chunk_a, chunk_b]
    repo.embeddings = {
        "P-01:c1": [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
        "P-02:c1": [0.8, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
    }

    class FixedVectorProvider(DeterministicProvider):
        def embed(self, texts):
            return [[1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]]

    service = RetrievalService(repo, FixedVectorProvider(), NullCache(), 300)
    results = service.search("kebijakan klaim kacamata", top_k=2)

    assert len(results) == 2
    assert results[0].chunk_id == "P-02:c1"
    assert results[0].score > results[1].score


def test_synonym_map_has_no_hardcoded_numbers() -> None:
    synonyms = RetrievalService._SYNONYM_MAP
    assert "12" not in synonyms["jatah"]
    assert "dua" not in synonyms["surat"]
    assert "dua" not in synonyms["dokter"]
    assert synonyms["jatah"] == "hak dan saldo cuti pegawai tetap"
    assert synonyms["surat"] == "cuti sakit pemberitahuan dokumen pendukung"
    assert synonyms["dokter"] == "cuti sakit pemberitahuan dokumen pendukung"
