# Submission Checklist

- [x] README dan perintah setup telah diuji dari environment bersih.
- [x] `Dockerfile` lengkap; image API/UI dibangun tanpa API key saat build dan berjalan sebagai user non-root.
- [x] `.dockerignore` mencegah `.env`, venv, cache, dan output lokal masuk image.
- [x] Dari checkout bersih, grader dapat menjalankan urutan `docker compose` pada `docker-delivery.md` tanpa Python/pip di host, memakai project name unik.
- [x] Seed, deterministic tests dalam container, `/healthz`, `/readyz` (`ready`), OpenAPI, dan UI Streamlit berhasil setelah `.env` instruktur disediakan.
- [x] Diagram arsitektur menunjukkan trust boundary, cache, telemetry, dan confirmation flow.
- [x] FastAPI terhubung ke Streamlit yang disediakan.
- [x] Policy indexing menghasilkan chunk versioned dan vector yang sesuai dimensi.
- [x] Pertanyaan kebijakan menampilkan sitasi valid.
- [x] Akses lintas pegawai diblokir.
- [x] Proposal tidak menulis leave request sebelum konfirmasi.
- [x] Konfirmasi ulang dengan key sama tidak membuat duplicate.
- [x] Semua request yang dibuat berstatus `pending_manager_review`.
- [x] `pytest -m "not live"` lulus.
- [x] Live evaluation report berisi minimal 15 kasus.
- [x] Risk register memiliki owner, mitigation, dan evidence.
- [x] Screenshot UI, monitoring, dan hasil test tersedia.
- [x] Demo 5–7 menit telah dilatih dengan backup output.

