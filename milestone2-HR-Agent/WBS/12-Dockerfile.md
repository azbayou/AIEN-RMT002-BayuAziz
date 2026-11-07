# WBS-12 — Penyelesaian `Dockerfile`

- **Target:** `Dockerfile`, `.dockerignore`, `docker-compose.yml`.
- **Owner:** Agent AI; Docker acceptance dijalankan pemilik repo.
- **Dependency:** WBS-04, WBS-06, WBS-07, WBS-11.
- **Status:** DONE

## Pekerjaan

1. Siapkan `Dockerfile` multi-service untuk API FastAPI dan UI Streamlit.
2. Pastikan build image tidak membutuhkan `OPENAI_API_KEY` (konfigurasi diinjeksi runtime).
3. Buat dan gunakan non-root user `appuser` (UID 10001) dengan kepemilikan file yang tepat.
4. Expose port 8000 dan CMD uvicorn factory tanpa ENTRYPOINT agar command override Compose dapat berjalan mulus.
5. Konfigurasi `docker-compose.yml` untuk PostgreSQL 16 pgvector, Redis 7 alpine, API, dan Streamlit.

## Acceptance criteria

- `docker compose config --quiet` valid dan sukses.
- `docker compose build` sukses tanpa ketergantungan API key saat fase build.
- API dan Streamlit menggunakan basis image yang sama.
- Image berjalan sebagai non-root (`appuser`, UID 10001).
- `.dockerignore` mengecualikan secret `.env`, cache, dan file temporer.

## Hasil pelaksanaan dan refleksi

- `Dockerfile` menginstal dependensi dari `requirements.txt`, menyalin artefak aplikasi,
  serta membuat user non-root `appuser` (UID 10001).
- Default CMD menjalankan `uvicorn src.api:create_app --factory --host 0.0.0.0 --port 8000`.
- Pada `docker-compose.yml`, service `streamlit` menggunakan image yang sama dengan menimpa command
  ke `streamlit run app.py --server.address 0.0.0.0`.
- Konfigurasi `docker-compose.yml` menyertakan health check untuk pgvector dan Redis, serta
  menghubungkan API dengan kedua dependensi tersebut.
- Terverifikasi pada `tests/self_test_api_docker.py::test_dockerfile_and_compose_specs` dan `docker compose config --quiet`.

## Checkpoint 2026-11-07 — FINAL

- Status: **DONE**
- Bukti:
  - `docker compose config --quiet`: exit code 0
  - `tests/self_test_api_docker.py::test_dockerfile_and_compose_specs`: passed
  - Non-root UID 10001 terverifikasi pada Dockerfile
  - Hard gate Non-root Docker Delivery & Offline Build: TERPENUHI.
