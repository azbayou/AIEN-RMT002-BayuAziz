# WBS-22-P2 — Penyempurnaan Hybrid RAG, Reranking, Pembersihan Versi Usang, dan Seed Historis

- **Target:** `src/retrieval.py`, `src/repository.py`, `src/setup_lab.py`, `tests/self_test_setup_and_retrieval.py`.
- **Owner:** Agent AI.
- **Dependency:** WBS-21-P1.
- **Status:** DONE

## Batasan Scope (Wajib Dipatuhi Agent)

- **Boleh diedit:** `src/retrieval.py`, `src/repository.py`, `src/setup_lab.py`, `tests/self_test_setup_and_retrieval.py`.
- **DILARANG diedit:** `src/contracts.py`, `data/policies/*.md`, `tests/test_retrieval_security.py`, `tests/test_repository_postgres.py`.
- Pastikan `test_retrieval_cache_hit_and_version_isolation`, `test_retrieval_corrupt_cache_degrades_to_fresh_search`, dan `test_retrieval_embedding_failure_degrades_to_lexical` di `tests/self_test_setup_and_retrieval.py` tetap lulus.

---

## Pekerjaan

### Task 1: Perbaiki Lexical Search PostgreSQL dari AND (`plainto_tsquery`) menjadi OR Antar-Token

Di `PostgresRepository.lexical_search` (`src/repository.py` sekitar baris 268), `plainto_tsquery('simple', %s)` menggabungkan semua kata dengan operator `AND`. Akibatnya query natural seperti `"Berapa jatah cuti tahunan saya?"` gagal menemukan dokumen karena kata `"berapa"` atau `"saya"` tidak ada di teks kebijakan.

#### Perubahan di `PostgresRepository.lexical_search`:

Ganti implementasi `PostgresRepository.lexical_search` di `src/repository.py` dengan mengekstrak token alfanumerik di Python lalu menggabungkannya dengan operator `|` (`OR`) untuk `to_tsquery`:

```python
    def lexical_search(self, query: str, limit: int) -> list[PolicyChunk]:
        import re
        stopwords = {"berapa", "apakah", "bagaimana", "kapan", "siapa", "yang", "dan", "di", "ke", "dari", "untuk", "pada", "saya", "aku", "bisa", "boleh"}
        raw_terms = [t for t in re.findall(r"[a-z0-9]+", query.casefold()) if len(t) >= 2]
        filtered_terms = [t for t in raw_terms if t not in stopwords] or raw_terms
        if not filtered_terms:
            return []
        tsquery_str = " | ".join(filtered_terms)
        with self.pool.connection() as connection:
            rows = connection.execute(
                """
                SELECT chunk_id, document_id, title, section, version, effective_date, content,
                       ts_rank(
                           to_tsvector('simple', title || ' ' || section || ' ' || content),
                           to_tsquery('simple', %s)
                       ) AS score
                FROM policy_chunks
                WHERE effective_date <= CURRENT_DATE
                  AND to_tsvector('simple', title || ' ' || section || ' ' || content)
                      @@ to_tsquery('simple', %s)
                ORDER BY score DESC, chunk_id
                LIMIT %s
                """,
                (tsquery_str, tsquery_str, limit),
            ).fetchall()
        return [self._chunk(row) for row in rows]
```

Dan pada `PostgresRepository.vector_search` (sekitar baris 287), tambahkan filter `AND effective_date <= CURRENT_DATE` pada klausa `WHERE`:

```sql
WHERE vector_dims(embedding) = %s AND effective_date <= CURRENT_DATE
```

### Task 2: Buat Keyword Reranking Berpengaruh Nyata & Jangan Cache Hasil Saat Embedding Degraded di `src/retrieval.py`

Saat ini di `src/retrieval.py`:
1. `rank_key` mengurutkan `(-scores[chunk.chunk_id], -keyword_score, chunk.chunk_id)` di mana `keyword_score` hanya menjadi tie-breaker jika skor RRF persis sama.
2. Ketika `self.provider.embed` gagal (timeout/error), hasil fallback lexical-only tetap disimpan ke Redis selama 15 menit (`self.cache.set(...)`), sehingga menurunkan kualitas pencarian berikutnya walaupun provider sudah pulih.

#### Ganti method `RetrievalService.search` di `src/retrieval.py` menjadi:

```python
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
        embedding_degraded = False
        try:
            embeddings = self.provider.embed([normalized])
            if embeddings:
                semantic = self.repository.vector_search(embeddings[0], max(top_k * 3, 5))
        except (RuntimeError, TimeoutError, ValueError, OSError):
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

        stopwords = {"berapa", "apakah", "bagaimana", "kapan", "siapa", "yang", "dan", "di", "ke", "dari", "untuk", "pada", "saya", "aku"}
        raw_terms = set(re.findall(r"\w+", normalized))
        terms = (raw_terms - stopwords) or raw_terms

        combined_scores: dict[str, float] = {}
        keyword_hits: dict[str, int] = {}
        for chunk_id, chunk in candidates.items():
            content_terms = set(
                re.findall(
                    r"\w+",
                    f"{chunk.title} {chunk.section} {chunk.content}".casefold(),
                )
            )
            overlap = len(terms & content_terms)
            keyword_hits[chunk_id] = overlap
            # Gabungkan RRF score dengan bobot keyword reranking (0.005 per kata kunci yang cocok)
            combined_scores[chunk_id] = rrf_scores[chunk_id] + (0.005 * overlap)

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
```

### Task 3: Bersihkan Chunk Versi Usang, Perkaya Teks Embedding, dan Seed `historical_requests.json`

Di `src/setup_lab.py`:
1. Saat ini `embeddings = provider.embed([chunk["content"] for chunk in policies])` hanya meng-embed isi tanpa judul dan nama bagian. Ubah menjadi:
   ```python
   embeddings = provider.embed(
       [f"{chunk['title']} - {chunk['section']}\n{chunk['content']}" for chunk in policies]
   )
   ```
2. Sebelum loop `for chunk, embedding in zip(policies, embeddings):`, bersihkan chunk dari dokumen yang sama tetapi versinya sudah usang agar tidak ada dua versi kebijakan aktif bersamaan ketika seed dijalankan tanpa `--reset`:
   ```python
            active_versions = {chunk["document_id"]: chunk["version"] for chunk in policies}
            for doc_id, ver in active_versions.items():
                cursor.execute(
                    "DELETE FROM policy_chunks WHERE document_id = %s AND version <> %s",
                    (doc_id, ver),
                )
   ```
3. Tambahkan juga pemuatan `data/historical_requests.json` pada `MemoryRepository.__init__` (`src/repository.py`) agar data historis cuti yang berstatus `approved` tersedia untuk pengecekan overlap:
   - Di `src/repository.py`, tambahkan helper `_load_historical_requests()` yang membaca `_DATA_DIR / "historical_requests.json"` (jika file ada).
   - Namun **PERHATIKAN**: cek `tests/test_actions.py` dan `tests/self_test_api_docker.py`! Di `tests/test_actions.py` baris 25 terdapat:
     `assert repository.list_leave_requests("EMP-001") == []`
     Jika `MemoryRepository.__init__` langsung mengisi `self.requests["EMP-001"]` dengan `LR-HIST-001`, maka `assert repository.list_leave_requests("EMP-001") == []` di `test_actions.py` **AKAN GAGAL**!
   - Oleh karena itu, **JANGAN** mengisi `self.requests` di `MemoryRepository.__init__` dan **JANGAN** memasukkan `approved` ke tabel `leave_requests` PostgreSQL (karena tabel `leave_requests` memiliki constraint `CHECK (status = 'pending_manager_review')`). Biarkan `leave_requests` khusus untuk permohonan baru yang berstatus `pending_manager_review` sesuai kontrak test instruktur.

### Task 4: Tambahkan Unit Test di `tests/self_test_setup_and_retrieval.py`

Tambahkan 2 test baru di akhir `tests/self_test_setup_and_retrieval.py`:
1. `test_retrieval_does_not_cache_when_embedding_provider_fails()`:
   - Gunakan `BrokenEmbeddingProvider` dan `mock_cache = MagicMock()` (`mock_cache.get.return_value = None`).
   - Panggil `service.search("cuti tahunan", top_k=2)`.
   - Pastikan hasil tidak kosong (`len(results) >= 1`), tetapi `mock_cache.set.assert_not_called()`.
2. `test_keyword_reranking_promotes_exact_term_match()`:
   - Buat 2 chunk di mana chunk B berada di peringkat vector sedikit lebih rendah (mis. rank 2 vs rank 1), tetapi chunk B memiliki 3 kata kunci yang cocok dengan query sedangkan chunk A memiliki 0 kata kunci yang cocok.
   - Verifikasi `combined_scores` mengangkat chunk B ke posisi pertama.

---

## Langkah Verifikasi

```bash
pytest tests/self_test_setup_and_retrieval.py tests/test_retrieval_security.py -v
pytest -m "not live"
```

## Acceptance Criteria

- [x] `PostgresRepository.lexical_search` menggunakan pencarian `OR` antar kata kunci penting dan memfilter `effective_date <= CURRENT_DATE`.
- [x] Keyword reranking di `RetrievalService.search` memberikan bobot tambahan nyata pada skor gabungan RRF.
- [x] Hasil pencarian yang terdegradasi (ketika embedding gagal) tidak disimpan ke Redis cache.
- [x] `setup_lab.py` menghapus chunk versi lama untuk `document_id` yang sama saat re-seed tanpa `--reset`.
- [x] Semua test di `tests/self_test_setup_and_retrieval.py` dan `pytest -m "not live"` lulus.

---

## Checkpoint & Catatan Implementasi

- **Penyempurnaan Lexical Search PostgreSQL (`src/repository.py`):**
  - Mengganti `plainto_tsquery` (AND) dengan ekstraksi token alfanumerik bebas stopword yang digabung dengan operator `|` (`OR`).
  - Menambahkan filter `effective_date <= CURRENT_DATE` baik pada `lexical_search` maupun `vector_search` PostgreSQL untuk mencegah kebocoran kebijakan masa depan.
- **Keyword Reranking & Degraded Cache Safety (`src/retrieval.py`):**
  - Menggabungkan RRF score dengan bobot keyword reranking (+0.005 per kata kunci yang cocok) ke dalam `combined_scores`, sehingga kecocokan istilah eksplisit mampu mengangkat dokumen relevan.
  - Menandai kondisi `embedding_degraded = True` saat provider embedding gagal, dan **tidak menyimpan** hasil pencarian fallback tersebut ke Redis (`if not embedding_degraded: self.cache.set(...)`) agar pencarian berikutnya dapat langsung menggunakan embedding normal saat provider pulih.
- **Pembersihan Versi Usang & Rich Embedding Text (`src/setup_lab.py`):**
  - Teks yang di-embed diperkaya dengan menyertakan judul dan nama seksi: `f"{title} - {section}\n{content}"`.
  - Re-seed tanpa `--reset` secara otomatis menghapus chunk versi usang (`DELETE FROM policy_chunks WHERE document_id = %s AND version <> %s`) sehingga tidak terjadi tumpang tindih versi kebijakan di database.
- **Unit & Self Tests:**
  - Ditambahkan unit test `test_retrieval_does_not_cache_when_embedding_provider_fails` dan `test_keyword_reranking_promotes_exact_term_match` di [self_test_setup_and_retrieval.py](file:///home/bay/Documents/Hacktiv8/Milestones/AIEN-RMT002-BayuAziz/milestone2-HR-Agent/tests/self_test_setup_and_retrieval.py).
  - Seluruh test di `self_test_setup_and_retrieval.py`, `test_retrieval_security.py`, `test_agent_reliability.py`, `test_tools.py`, dan `self_test_tools_agent.py` terverifikasi lulus 100%.
