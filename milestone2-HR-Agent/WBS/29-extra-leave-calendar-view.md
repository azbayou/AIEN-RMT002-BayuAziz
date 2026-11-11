# WBS-29-extra — Kalender Jadwal Cuti Interaktif (Team & Personal Leave Calendar View)

- **Target:** `app2.py`, `WBS/29-extra-leave-calendar-view.md`.
- **Owner:** Agent AI.
- **Dependency:** WBS-24-extra, WBS-25-extra, WBS-28-extra.
- **Status:** DONE

## Batasan Scope & Guardrail Penilaian (Dipatuhi Penuh)

- **Boleh diedit:** `app2.py`, `WBS/29-extra-leave-calendar-view.md`.
- **DILARANG KERAS diedit:** `requirements.txt`, `Dockerfile`, `app.py`, `ui_contract.py`, `demo_personas.json`, `tests/test_*.py` (test bawaan instruktur).
- **Zero New Dependencies:** Seluruh fungsionalitas kalender dibangun menggunakan pustaka standar bawaan Python (`calendar`, `datetime`) dan elemen Streamlit bawaan (HTML/CSS Grid kustom). Tidak ada pustaka eksternal pihak ketiga baru yang ditambahkan ke `requirements.txt`.
- **Kepatuhan Privasi Data (`HR-PRIV-001` / `data/policies/privacy.md`):**
  1. Pegawai biasa (`role: employee`) hanya melihat jadwal cuti miliknya sendiri (*Kalender Cuti Saya*) agar data medis rekan kerja tetap terlindungi.
  2. Manajer (`role: manager`) dan Admin (`role: monitoring_admin`) dapat mengakses *Kalender Tim & Departemen* untuk melihat distribusi cuti bawahan langsung guna mencegah *understaffing*, atau beralih ke *Kalender Cuti Saya*.

---

## Rincian Implementasi & Hasil

### Task 1: Pemetaan Data Kalender Dinamis di `app2.py`
1. Membuat fungsi `build_calendar_leave_map(requests: list[dict], year: int, month: int) -> dict[date, list[dict]]`:
   - Memetakan setiap permohonan cuti aktif (`approved` dan `pending_manager_review`) ke tanggal-tanggal spesifik pada bulan dan tahun yang dipilih.
   - Menangani permohonan yang melintasi pergantian bulan (*cross-month boundary*) dengan kalkulasi clamp rentang tanggal `eff_start` dan `eff_end`.
   - Mengisi metadata per tanggal: nama pegawai, ID pegawai, ID permohonan, jenis cuti (`annual`, `sick`, `parental`), status permohonan, durasi hari kerja, dan alasan.

### Task 2: Komponen Tampilan Kalender Visual Grid (Dark Modern Theme)
1. Membuat fungsi `render_leave_calendar(token: str, persona: dict, is_manager: bool, is_admin: bool)`:
   - Navigasi bulan interaktif: tombol `◀`, dropdown pilihan nama bulan (Januari–Desember), dropdown pilihan tahun, tombol `▶`, dan tombol jalan pintas `📍 Hari Ini`.
     - *Sinkronisasi State Streamlit:* Menggunakan callback resmi `on_click` (`_prev_cal_month`, `_next_cal_month`, `_today_cal_month`) dan `on_change` (`_on_cal_month_change`, `_on_cal_year_change`) agar perpindahan bulan via tombol maupun dropdown selectbox selalu tersinkronisasi dua arah tanpa tertimpa widget key state Streamlit.
   - Filter cepat berdasarkan:
     - Jenis cuti: `Semua Jenis Cuti`, `Tahunan (Annual)`, `Sakit (Sick)`, `Orang Tua (Parental)`.
     - Status permohonan: `Semua Status Aktif`, `Hanya Disetujui (Approved)`, `Menunggu Review (Pending)`.
   - Grid 7 kolom (Senin–Minggu) menggunakan `calendar.Calendar(firstweekday=0).monthdatescalendar(year, month)`:
     - Highlight tanggal hari ini (`today`, border biru `#38bdf8` dan badge `HARI INI`).
     - Aksen khusus akhir pekan (Sabtu & Minggu berwarna merah muda `#f87171` dan background redup).
     - Sel kosong di luar bulan aktif (`calendar-cell empty`) dengan angka pudar.
   - Penanda warna dan badge permohonan cuti:
     - 🟢 **Hijau (`calendar-badge-annual`)**: Cuti Tahunan (*Annual Leave*).
     - 🔴 **Merah/Rose (`calendar-badge-sick`)**: Cuti Sakit (*Sick Leave*).
     - 🟣 **Ungu (`calendar-badge-parental`)**: Cuti Orang Tua (*Parental Leave*).
     - *Border solid*: Status `approved` (Disetujui).
     - *Border dashed*: Status `pending_manager_review` (Menunggu Review).
     - Tooltip HTML `title` lengkap memuat: Nama Pegawai, ID Pegawai, Jenis Cuti, Status, Rentang Tanggal, Durasi Hari Kerja, dan Alasan Cuti.
     - Penanganan overflow: menampilkan maksimal 2 badge teratas dan badge indikator `+{n} lainnya...` jika ada lebih dari 3 cuti pada 1 tanggal.
   - Legenda kalender interaktif untuk mempermudah identifikasi visual.
   - Metrik ringkasan bulanan:
     - Total Pengajuan Bulan Ini
     - Hari Terisi Cuti
     - Hari Puncak Cuti (Tanggal dengan cuti terbanyak)
     - Jumlah Permohonan Menunggu Keputusan
   - Expander drilldown: `📋 Rincian Lengkap Permohonan Cuti ({Bulan} {Tahun})` dengan kartu detail dan badge status per permohonan.

### Task 3: Integrasi Tab `📅 Kalender Cuti` pada Navigasi Utama `app2.py`
1. Menambahkan tab `📅 Kalender Cuti` pada percabangan role:
   - Pegawai: `["💬 Percakapan Interaktif", "📋 Permintaan Cuti Saya", "📅 Kalender Cuti"]`
   - Manajer: `["💬 Percakapan Interaktif", "📋 Permintaan Cuti Saya", "📅 Kalender Cuti", "✅ Persetujuan Cuti Tim"]`
   - Admin: `["💬 Percakapan Interaktif", "📋 Permintaan Cuti Saya", "📅 Kalender Cuti", "✅ Persetujuan Cuti Tim", "📊 Monitoring Operasional"]`
2. Memanggil `with tab_calendar: render_leave_calendar(token, persona, is_manager, is_admin)`.

### Task 4: Verifikasi & Test Suite
1. `python3 -m py_compile app2.py`: **Passed (Exit code 0)**.
2. `pytest tests/test_*.py tests/self_test_*.py`: **108 passed, 4 skipped in 4.39s (100% kelulusan)**.
