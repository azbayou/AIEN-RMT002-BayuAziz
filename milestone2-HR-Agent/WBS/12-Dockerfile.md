# WBS-12 — Penyelesaian `Dockerfile`

- **Target:** `Dockerfile`, `.dockerignore`, `docker-compose.yml`.
- **Owner:** Agent AI; Docker acceptance dijalankan pemilik repo.
- **Dependency:** WBS-04, WBS-06, WBS-07, WBS-11.
- **Status:** CHECKPOINT - IMPLEMENTED

## Pekerjaan

1. Install `requirements.txt`.
2. Copy `src/`, `data/`, `app.py`, `ui_contract.py`, `demo_personas.json`, dan `tests/`.
3. Buat user non-root dan atur read permissions.
4. Expose 8000 dan CMD uvicorn factory.
5. Pastikan Compose command override tetap bisa menjalankan seed dan test.

## Acceptance criteria

- `docker compose build api streamlit` sukses tanpa API key.
- API dan Streamlit start dari image yang sama.
- `docker compose run --rm api python -m src.setup_lab` dan pytest dapat berjalan.
- `docker inspect` menunjukkan proses bukan root.

## Checkpoint

- Image menginstal `requirements.txt`, menyalin source/data/tests dan artefak UI yang
  dibutuhkan oleh API serta Streamlit.
- Image membuat dan memakai user non-root `appuser` dengan UID 10001.
- Port 8000 diekspos dan default command menjalankan uvicorn factory tanpa ENTRYPOINT,
  sehingga Compose dapat mengganti command untuk Streamlit, seed, atau pytest.
- `.dockerignore` sudah mengecualikan `.env`, virtual environment, cache, database lokal,
  log, dan output evaluasi.
- `docker compose config --quiet` dan `docker compose build api streamlit` berhasil tanpa
  API key.
- Image inspection menunjukkan `USER=appuser`, port `8000`, dan default uvicorn command.
- Test API/agent dari dalam image: `7 passed`; kompilasi source dalam image juga berhasil.

## TODO berikutnya

1. Jalankan container hasil build sebagai API dan Streamlit, lalu cek `/healthz`, `/readyz`,
   dan proses non-root dengan `docker inspect`.
2. Jalankan seed dan suite pytest dari container setelah PostgreSQL/Redis tersedia.
3. Review `build_runtime`/`PostgresRepository` sebelum menganggap delivery production final.
