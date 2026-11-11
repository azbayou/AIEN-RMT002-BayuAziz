# WBS-30-extra — Rombak Total UI/UX dengan Streamlit Tailwind (Clean & Zero-Emoticon)

- **Target:** `app2.py`, `public/style.css`, `ui/` (seluruh sub-modul), `WBS/30-extra-ui-ux.md`.
- **Owner:** Agent AI & User (Brainstorming & Implementation).
- **Dependency:** WBS-24-extra (Revisi Sub-App Session Selector), WBS-25-extra s/d WBS-29-extra.
- **Status:** DONE (Modular ui/ Architecture, External CSS & Zero-Emoticon Verified)

---

## 1. Visi Desain & Prinsip Utama

0. **Pemisahan Modular ke Folder `ui/` & File CSS Eksternal (`public/style.css`):**
   - **Pemecahan Monolit `app2.py`:** Memecah `app2.py` yang saat ini mencapai ~2.100 baris menjadi modul-modul sub-fitur di folder `ui/`, sehingga `app2.py` terpangkas menjadi ~100–120 baris murni sebagai *clean orchestrator*.
   - **Struktur Folder `ui/`:**
     - `ui/__init__.py`: Package marker.
     - `ui/config.py`: Inisialisasi konfigurasi dasar, konstanta paths, loader aset, dan CSS loader (`public/style.css`) beserta session state tema (`ui_theme`).
     - `ui/api_client.py`: Client HTTP (`api_request`, `get_health_status`, daemon runner FastAPI latar belakang).
     - `ui/policy_rag.py`: Helper dinamis analisis kebijakan cuti berbasis AI/RAG (`get_annual_leave_lead_days_from_policy`, `get_sick_leave_doc_threshold_from_policy`, `get_parental_leave_policy_summary`, `get_annual_leave_entitlement_from_policy`, `has_leave_intent`, `get_min_start_date`). **Dilarang hardcode angka/kebijakan; selalu gunakan query RAG dengan fallback file lokal**.
     - `ui/leave_form.py`: Formulir pengajuan cuti interaktif & modal dialog Streamlit (`render_leave_form`, `leave_dialog`).
     - `ui/session_selector.py`: [WBS-24] Halaman Sub-App User Directory (membaca dinamis dari `data/employees.json`): Alya & Bima direct login mengikat Bearer token masing-masing, Raka & Admin step-up password verification via `POST /api/v1/auth/login`.
     - `ui/sidebar.py`: Kartu profil aktif, quick prompts, tombol ganti sesi pengguna, tombol trigger tema Gelap/Terang, dan indikator koneksi database.
     - `ui/tab_chat.py`: Tab 1 — Percakapan interaktif Miyo, STT input suara, konfirmasi proposal tindakan ganda/tunggal, dan sitasi kebijakan terverifikasi.
     - `ui/tab_requests.py`: Tab 2 — Pelacak permohonan cuti aktif/historis pengguna login + preview & upload lampiran surat dokter.
     - `ui/tab_calendar.py`: Tab 3 — [WBS-29] Kalender cuti interaktif (grid Senin–Minggu, filter jenis cuti & status, badges warna, navigasi bulan/tahun bebas bug).
     - `ui/tab_approvals.py`: Tab 4 — Persetujuan cuti anggota tim untuk Manager & Admin, review keputusan (setujui/tolak), dan ringkasan analitik tim.
     - `ui/tab_monitoring.py`: Tab 5 — Monitoring operasional dan audit SLI/SLA untuk Admin (telemetry, alerts, organisasi SDM).

1. **Zero-Hardcode & Dynamic Data Flow:**
   - **Daftar User Dinamis:** Membaca profil dari `data/employees.json` (bukan daftar hardcoded di UI), mengekstrak username, display name, role, department, dan token.
   - **Ketentuan Cuti Dinamis:** Syarat batas H-x cuti tahunan, ambang batas hari cuti sakit tanpa surat dokter, dan kelayakan masa kerja cuti orang tua selalu dibaca secara dinamis dari Agent/RAG PostgreSQL vector search (`search_hr_policy`) dengan fallback membaca markdown file di `data/policies/`.
   - **Tahun Dinamis pada Kalender:** Rentang tahun pada dropdown kalender dihitung relatif terhadap `date.today().year` secara dinamis.

2. **Zero-Emoticon Policy (100% Bebas Emoji/Emoticon):**
   - Menghapus **seluruh** penggunaan karakter emoji/emoticon di setiap sudut antarmuka `app2.py` dan modul `ui/` (navigasi tab, tombol aksi, judul halaman, kartu profil, chat avatar, badge status, kalender cuti, peringatan/alert, dan expander).
   - Mengganti fungsi penanda visual dengan:
     - **Tipografi Berhirarki Tinggi:** Kontras ketebalan font (`font-medium`, `font-semibold`, `font-bold`), label kapital terstruktur (`text-xs uppercase tracking-wider`), dan *monospace pill* (`font-mono text-xs`) untuk ID entitas (`EMP-001`, `MGR-001`, `HR-LEAVE-001`).
     - **Indikator Geometris & Status Dot CSS:** Titik indikator bulat berbasis CSS murni (`inline-block w-2 h-2 rounded-full`) serta aksen garis tepi (`border-l-2` / `border-l-4`) untuk menandai status sistem dan kategori cuti.
     - **Teks Bersih & Simbol ASCII Fungsional:** Menggunakan teks eksplisit (`Sebelumnya`, `Berikutnya`, `Disetujui`, `Menunggu Review`) menggantikan ikon-ikon dekoratif.

3. **Pendekatan Styling: Streamlit + Tailwind CSS Utility Architecture dengan Dual-Theme Engine (Dark / Light Toggle):**
   - Menyediakan **Tombol Trigger Tema Gelap / Terang (`Dark / Light Mode Toggle`)** yang tersimpan di `st.session_state["ui_theme"]` (`"dark"` atau `"light"`).
   - Tombol trigger ditempatkan di sudut kanan atas pada halaman *Sub-App User Selector* (`VIEW 1`) dan di bagian atas *Sidebar* pada halaman *Dashboard Utama* (`VIEW 2`), menggunakan label bersih tanpa emoticon (misalnya `Mode: Gelap` / `Mode: Terang` atau `st.toggle("Mode Terang")`).
   - Menerapkan sistem desain berbasis token Tailwind CSS (`slate`, `sky`, `emerald`, `amber`, `rose`, `violet`) yang dipetakan ke **CSS Variables Dinamis (`:root`)** sehingga pergantian tema mengubah seluruh elemen secara instan:
     - **Tema Gelap (`dark` — Dark Slate Enterprise):**
       - App Background: `#090d16` (`slate-950`), Surface/Sidebar: `#0f172a` (`slate-900`), Card: `#1e293b` (`slate-800`), Border: `#334155` (`slate-700`), Text Primary: `#f8fafc` (`slate-50`), Text Secondary: `#94a3b8` (`slate-400`), Accent: `#38bdf8` (`sky-400`).
     - **Tema Terang (`light` — Clean Corporate Light):**
       - App Background: `#f8fafc` (`slate-50`), Surface/Sidebar: `#f1f5f9` (`slate-100`), Card: `#ffffff` (`white`), Border: `#e2e8f0` (`slate-200`), Text Primary: `#0f172a` (`slate-900`), Text Secondary: `#475569` (`slate-600`), Accent: `#0284c7` (`sky-600`).
   - Meng-override kontainer native Streamlit (`[data-testid="stAppViewContainer"]`, `[data-testid="stSidebar"]`, `[data-testid="stHeader"]`, input form, selectbox, tabs, expander, metric, dan chat input) serta seluruh komponen HTML kustom (Kartu User, Sitasi, Proposal, Kalender Cuti) agar tidak ada warna statis (*hardcoded*) yang bertabrakan saat mode Terang atau Gelap diaktifkan.

4. **Batasan Scope & Guardrail Penilaian (Wajib Dipatuhi 100%):**
   - **Boleh diedit/dibuat:** `app2.py`, `public/style.css`, folder `ui/*`, `WBS/24-extra-db-account-dan-password-login.md`, `WBS/30-extra-ui-ux.md`.
   - **DILARANG KERAS diedit:** `requirements.txt`, `Dockerfile`, `app.py`, `ui_contract.py`, `demo_personas.json`, `tests/test_*.py` (test bawaan instruktur).
   - Seluruh test instruktur (`tests/test_*.py`) dan self-test (`tests/self_test_*.py`) wajib lulus 100% tanpa regresi.

---

## 2. Pemetaan Rombak Komponen UI di `app2.py`

### Area A: Sub-App Session Selector & Step-Up Authentication (`VIEW 1`)
Mengimplementasikan revisi **WBS-24-extra** dengan tampilan *Enterprise Sub-App Directory*:
- **Header Modul Bersih:** Menampilkan identitas perusahaan (`PT Nusantara Digital`) dan nama sub-aplikasi (`HR Policy & Leave Management System`) tanpa dekorasi berlebihan.
- **Daftar Pengguna Aktif (User Directory Grid / List) dengan Isolasi Bearer Token:**
  - Menampilkan 4 akun dari `data/employees.json`, di mana setiap sesi **wajib mengikat Bearer Token unik per akun** (`Authorization: Bearer <token>`) agar identitas, saldo cuti, proposal, dan riwayat permohonan cuti **tidak pernah tertukar antar pegawai**:
    1. **Alya Pratama** (`EMP-001` · `Engineering` · Badge: `EMPLOYEE` · Token: `token-alya`) -> Tombol: **Masuk Sesi** (*Direct SSO Access tanpa input password, otomatis mengikat `Bearer token-alya` dan mereset state sesi sebelumnya via `select_persona`*).
    2. **Bima Santoso** (`EMP-002` · `Engineering` · Badge: `EMPLOYEE` · Token: `token-bima`) -> Tombol: **Masuk Sesi** (*Direct SSO Access tanpa input password, otomatis mengikat `Bearer token-bima` dan mereset state sesi sebelumnya via `select_persona`*).
    3. **Rakabuming Raka** (`MGR-001` · `Engineering` · Badge: `MANAGER` · Status: `Step-Up Auth Required`) -> Tombol: **Verifikasi Akses** (*Memverifikasi password ke `POST /api/v1/auth/login` untuk mendapatkan `Bearer token-manager`*).
    4. **Monitoring Admin** (`ADM-001` · `HR & People Ops` · Badge: `ADMIN` · Status: `Step-Up Auth Required`) -> Tombol: **Verifikasi Akses** (*Memverifikasi password ke `POST /api/v1/auth/login` untuk mendapatkan `Bearer token-admin`*).
- **Panel Step-Up Password Re-Authentication:**
  - Muncul secara kontekstual ketika pengguna memilih akun `MANAGER` (`MGR-001`) atau `ADMIN` (`ADM-001`).
  - Menampilkan informasi akun yang akan diakses, input `Password Konfirmasi`, tombol `Konfirmasi & Masuk`, serta tombol `Batal`.

### Area B: Sidebar, Sesi Aktif & Navigasi Modul (Tabs di Sidebar Kiri)
- **Identitas Sesi:** Kartu profil bergaya Tailwind (`user-profile-card`) yang menampilkan Nama, `employee_id` (monospace), Departemen, dan Role Badge tanpa ikon orang/emoji.
- **Menu Navigasi Modul (Pindahan dari Horizontal Tabs ke Sidebar Kiri):**
  - Menggunakan styled vertical navigation tabs (berbasis `st.radio` dengan CSS kustom tanpa bullet radio) yang dinamis sesuai peran:
    - **Employee:** `["Asisten Kebijakan", "Permohonan Cuti Saya", "Kalender Cuti"]`
    - **Manager:** `["Asisten Kebijakan", "Permohonan Cuti Saya", "Kalender Cuti", "Persetujuan Tim"]`
    - **Monitoring Admin:** `["Asisten Kebijakan", "Permohonan Cuti Saya", "Kalender Cuti", "Persetujuan Tim", "Monitoring Operasional"]`
  - Item aktif ditandai dengan latar *Sky Blue Enterprise* (`var(--accent-sky)`), teks tebal putih, dan shadow halus.
- **Tombol Aksi & Sesi:**
  - Tombol `Formulir Pengajuan Cuti` (primary) untuk Pegawai & Manager.
  - Tombol `Ganti Sesi Pengguna` (secondary) yang mengembalikan tampilan ke *Sub-App User Selector*.
- **Indikator Kesehatan Sistem (Footer Sidebar):**
  - Menggunakan logo Gunungan dan indikator status teks murni (`[SISTEM AKTIF] Database & Layanan Siap`).

### Area C: Header Halaman Utama Adaptif
- Menampilkan logo Gunungan kecil dan judul modul aktif secara dinamis (`<h2>{selected_tab}</h2>`) mengikuti pilihan menu di sidebar kiri.
- Bebas dari horizontal `st.tabs` di area utama, membuat area kerja lebih luas, fokus, dan berperforma tinggi.

### Area D: Workspace Percakapan, Rekomendasi Pertanyaan & Toolbar Chat
- **Rekomendasi Pertanyaan di Dalam Chat:**
  - **Saat Percakapan Masih Kosong:** Kartu selamat datang (*Welcome Card*) menampilkan sapaan personal dan **grid 2 kolom kartu rekomendasi pertanyaan** interaktif (misal: jatah cuti, sisa saldo cuti, syarat surat dokter, aturan WFH, analitik cuti tim). Mengklik pertanyaan langsung memicu pengiriman pertanyaan ke Miyo.
  - **Saat Percakapan Sedang Berjalan:** Popover `Rekomendasi Pertanyaan` tersedia tepat di atas input chat berdampingan dengan `Input Suara (Mikrofon)` dan tombol `Hapus Chat`.
- **Chat Message & Avatar:**
  - Menggunakan logo resmi Miyo (`miyo.png`) untuk pesan asisten dan inisial teks bersih untuk pengguna.
- **Kartu Sitasi Kebijakan (`Citation Card`):**
  - Desain kartu Tailwind: `bg-slate-900 border border-slate-800 border-l-4 border-l-indigo-500 rounded-r-md p-3`.
  - Header sitasi menampilkan badge monospace `[DOC-ID]` diikuti judul dokumen dan bagian pasal.
- **Kartu Proposal Pengajuan Cuti (`Action Proposal Card`):**
  - Desain panel terstruktur dengan *header badge* `PROPOSAL PENGAJUAN CUTI`, grid metadata 2 kolom (Jenis Cuti, Periode Tanggal, Hari Kerja, Alasan), daftar poin validasi dengan tanda centang teks/SVG, serta tombol aksi `Konfirmasi Pengajuan` dan `Ubah via Formulir`.
- **Input Suara (Voice Input):**
  - Popover dengan label bersih `Input Suara ( Transkripsi Otomatis )` tanpa emoji mikrofon.

### Area E: Kalender Cuti Interaktif, Persetujuan Tim, & Monitoring
- **Kalender Cuti (`render_leave_calendar`):**
  - Navigasi menggunakan tombol teks bersih: `Sebelumnya`, dropdown Bulan & Tahun, `Berikutnya`, dan `Hari Ini`.
  - Sel tanggal menggunakan grid Tailwind (`grid-cols-7 gap-1.5`).
  - Penanda jenis cuti menggunakan *color-coded pill* tanpa emoji bulatan:
    - Cuti Tahunan: `bg-emerald-950/60 text-emerald-300 border border-emerald-600` (solid untuk *Approved*, dashed untuk *Pending*).
    - Cuti Sakit: `bg-rose-950/60 text-rose-300 border border-rose-600`.
    - Cuti Orang Tua: `bg-violet-950/60 text-violet-300 border border-violet-600`.
  - Banner privasi pegawai menggunakan gaya *callout card* Tailwind (`border-l-4 border-sky-500 bg-slate-900/80`) tanpa emoji gembok.
- **Persetujuan Cuti Tim & Monitoring Operasional:**
  - Kartu KPI menggunakan layout metrik bersih dengan label uppercase kecil (`text-xs uppercase tracking-wider text-slate-400`) dan angka utama tegas (`text-2xl font-semibold text-slate-100`).
  - Badge status menggunakan *pill* tegas: `MENUNGGU REVIEW`, `DISETUJUI`, `DITOLAK`.

---

## 3. Poin Brainstorming & Keputusan Desain

1. **[DISEPAKATI] Palet Warna & Trigger Gelap/Terang (Dual-Theme Toggle):**
   - Menyediakan tombol trigger interaktif untuk beralih antara **Dark Mode (`Dark Slate Enterprise`)** dan **Light Mode (`Clean Corporate Light`)** kapan saja, baik di halaman *Sub-App User Selector* maupun di dalam *Dashboard*.
   - Seluruh komponen (termasuk kalender cuti, kartu proposal, sitasi, dan komponen native Streamlit) menggunakan variabel CSS adaptif agar kontras teks dan latar belakang selalu terjaga di kedua mode.

2. **Layout Halaman Pilih User (Sub-App Session Selector):**
   - **Opsi A — 2x2 atau 4-Column Profile Cards:** Setiap user ditampilkan sebagai kartu profil lengkap dengan atribut departemen, role badge, ringkasan hak/akses, dan ketika Manager/Admin diklik, form password muncul tepat di dalam kartu tersebut atau di panel bawahnya.
   - **Opsi B — Enterprise Directory Table / List Row:** Daftar baris horizontal seperti daftar akun SSO perusahaan (Nama, ID, Departemen, Role Badge, dan tombol aksi di sisi kanan).

3. **Pengganti Ikon pada Navigasi & Status:**
   - **Opsi A — Pure Typography & CSS Dots:** Hanya teks bersih dan titik warna CSS (`w-2 h-2 rounded-full`), nol ikon sama sekali.
   - **Opsi B — Minimalist Inline SVG (Lucide/Heroicons style):** Menggunakan ikon garis vektor SVG monokrom ukuran `14px`–`16px` pada elemen tertentu (seperti panah kalender atau indikator kunci pada akun Manager/Admin).

---

## 4. Langkah Verifikasi (Hasil Eksekusi)

1. Audit otomatis dengan regex karakter Unicode emoji pada `app2.py` dan seluruh modul `ui/*.py`: **100% Bebas Emoticon/Emoji (0 matches)**.
2. Uji kompilasi sintaks: `python3 -m py_compile app2.py ui/*.py` -> **Sukses (Exit code 0)**.
3. Pemisahan arsitektur modular ke folder `ui/` dan file eksternal `public/style.css`:
   - `app2.py` terpangkas dari 2.099 baris menjadi **89 baris** murni sebagai clean orchestrator.
   - Styling terpusat di `public/style.css` (448 baris) dengan CSS Variables `:root` dan `[data-theme="light"]`.
4. Uji alur Sub-App Selector: Employee langsung masuk mengikat token unik (`token-alya`, `token-bima`), Manager (`MGR-001`) dan Admin (`ADM-001`) wajib Step-Up Password Authentication.
5. Jalankan seluruh test suite:
   - `pytest tests/test_*.py tests/self_test_*.py` -> **108 passed, 0 failed, 4 skipped**.

## Acceptance Criteria

- [x] Monolit `app2.py` dipecah ke folder `ui/` (`config`, `api_client`, `policy_rag`, `leave_form`, `session_selector`, `sidebar`, `tab_chat`, `tab_requests`, `tab_calendar`, `tab_approvals`, `tab_monitoring`).
- [x] Tab navigasi dipindahkan ke sidebar di sebelah kiri sebagai menu pill modern dinamis sesuai role pengguna.
- [x] Rekomendasi pertanyaan dipindahkan ke dalam chat (kartu selamat datang di awal percakapan dan popover di atas chat input).
- [x] CSS dipisahkan ke `public/style.css` dengan dukungan Dual-Theme Engine (Dark / Light toggle).
- [x] Zero-Emoticon Policy: 0 emoji pada seluruh antarmuka, navigasi, badge, formulir, dan kalender.
- [x] Sesi Employee (`EMP-001`, `EMP-002`) mengikat Bearer token unik (`token-alya`, `token-bima`) sehingga permohonan cuti tidak tertukar.
- [x] Manager dan Admin mewajibkan Step-Up password verification via `POST /api/v1/auth/login`.
- [x] Seluruh kriteria penilaian dan unit test lulus 100% tanpa regresi.
