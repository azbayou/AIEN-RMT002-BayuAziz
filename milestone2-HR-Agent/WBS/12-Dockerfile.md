# WBS-12 — Penyelesaian `Dockerfile`

- **Target:** `Dockerfile`, `.dockerignore`, `docker-compose.yml`.
- **Owner:** Agent AI; Docker acceptance dijalankan pemilik repo.
- **Dependency:** WBS-04, WBS-06, WBS-07, WBS-11.
- **Status:** TODO

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
