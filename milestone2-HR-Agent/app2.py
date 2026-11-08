"""Interactive Enterprise Streamlit UI with Multi-Persona Login Portal for Miyo HR Assistant."""
from __future__ import annotations

import os
import re
import threading
import time
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx
import streamlit as st

from ui_contract import API_PATHS, load_personas, select_persona

# ==============================================================================
# Configuration & Background API Runner (for Standalone / Streamlit Cloud)
# ==============================================================================
API_URL = os.getenv("API_URL", "http://localhost:8000").rstrip("/")


def _ensure_api_running() -> None:
    """If running in an all-in-one environment without an external API, start FastAPI in background."""
    if "api" in API_URL or "onrender.com" in API_URL:
        return
    if "FASTAPI_DAEMON_STARTED" not in st.session_state:
        st.session_state["FASTAPI_DAEMON_STARTED"] = True
        try:
            httpx.get(f"{API_URL}/healthz", timeout=1.0)
        except Exception:
            try:
                import uvicorn
                from src.api import create_app

                app_instance = create_app()

                def _start_server():
                    uvicorn.run(app_instance, host="127.0.0.1", port=8000, log_level="warning")

                server_thread = threading.Thread(target=_start_server, daemon=True)
                server_thread.start()
                time.sleep(1.5)
            except Exception:
                pass


_ensure_api_running()

# ==============================================================================
# Brand Assets & Paths
# ==============================================================================
GUNUNGAN_LOGO = str(Path(__file__).resolve().parent / "public" / "img" / "gunungan.png")
MIYO_LOGO = str(Path(__file__).resolve().parent / "public" / "img" / "miyo.png")

# ==============================================================================
# Page Setup & Custom CSS Styling
# ==============================================================================
st.set_page_config(
    page_title="Miyo — Asisten HR Nusantara Digital",
    page_icon=MIYO_LOGO if os.path.exists(MIYO_LOGO) else "🧭",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
    /* Global container adjustments */
    .block-container {
        padding-top: 1.8rem;
        padding-bottom: 2rem;
    }
    
    /* Login Portal Cards */
    .login-hero {
        text-align: center;
        padding: 1.5rem 1rem 1.8rem 1rem;
    }
    .login-badge {
        display: inline-block;
        background-color: #0369a1;
        color: #e0f2fe;
        font-size: 0.8rem;
        font-weight: 700;
        letter-spacing: 0.05em;
        padding: 4px 12px;
        border-radius: 9999px;
        margin-bottom: 0.8rem;
        text-transform: uppercase;
    }
    .persona-login-card {
        background: linear-gradient(145deg, #1e293b 0%, #0f172a 100%);
        border: 1px solid #334155;
        border-radius: 14px;
        padding: 20px 18px;
        text-align: center;
        height: 100%;
        display: flex;
        flex-direction: column;
        justify-content: space-between;
        box-shadow: 0 4px 14px rgba(0, 0, 0, 0.25);
        transition: transform 0.2s, border-color 0.2s;
    }
    .persona-login-card:hover {
        border-color: #38bdf8;
        transform: translateY(-2px);
    }
    .persona-avatar {
        font-size: 2.8rem;
        margin-bottom: 8px;
    }
    .persona-login-name {
        font-weight: 800;
        font-size: 1.15rem;
        color: #f8fafc;
        margin-bottom: 4px;
    }
    .persona-login-role {
        font-size: 0.82rem;
        color: #38bdf8;
        font-weight: 600;
        margin-bottom: 10px;
    }
    .persona-login-desc {
        font-size: 0.85rem;
        color: #94a3b8;
        line-height: 1.4;
        margin-bottom: 14px;
    }

    /* Sidebar Active User Card */
    .user-profile-card {
        background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%);
        border: 1px solid #38bdf8;
        border-radius: 12px;
        padding: 14px 16px;
        margin-bottom: 15px;
        color: #f8fafc;
    }
    .user-profile-name {
        font-weight: 700;
        font-size: 1.1rem;
        color: #38bdf8;
    }
    .user-profile-role {
        font-size: 0.82rem;
        color: #94a3b8;
        margin-bottom: 6px;
    }
    .user-profile-scenario {
        font-size: 0.85rem;
        color: #cbd5e1;
        line-height: 1.35;
    }

    /* Proposal Card */
    .proposal-box {
        background-color: #0f172a;
        border: 2px solid #38bdf8;
        border-radius: 12px;
        padding: 18px 20px;
        margin-top: 12px;
        margin-bottom: 12px;
        box-shadow: 0 4px 14px rgba(56, 189, 248, 0.15);
    }
    .proposal-title {
        font-size: 1.1rem;
        font-weight: 700;
        color: #38bdf8;
        display: flex;
        align-items: center;
        gap: 8px;
        margin-bottom: 10px;
    }
    .proposal-detail {
        font-size: 0.95rem;
        color: #e2e8f0;
        margin: 4px 0;
    }
    .validation-badge {
        display: inline-block;
        background-color: #064e3b;
        color: #6ee7b7;
        padding: 2px 10px;
        border-radius: 6px;
        font-size: 0.82rem;
        margin-top: 8px;
        margin-right: 6px;
    }
    .expiry-tag {
        display: inline-block;
        background-color: #451a03;
        color: #fcd34d;
        padding: 2px 10px;
        border-radius: 6px;
        font-size: 0.82rem;
        margin-top: 8px;
    }

    /* Citation Card */
    .citation-card {
        background-color: #1e293b;
        border-left: 4px solid #6366f1;
        border-radius: 4px 8px 8px 4px;
        padding: 10px 14px;
        margin-top: 8px;
        margin-bottom: 8px;
    }
    .citation-header {
        font-weight: 600;
        color: #a5b4fc;
        font-size: 0.9rem;
    }
    .citation-body {
        font-size: 0.85rem;
        color: #cbd5e1;
        margin-top: 4px;
    }

    /* Status Badges */
    .status-badge-pending {
        background-color: #78350f;
        color: #fde68a;
        padding: 4px 12px;
        border-radius: 9999px;
        font-size: 0.82rem;
        font-weight: 600;
    }
    .status-badge-approved {
        background-color: #064e3b;
        color: #6ee7b7;
        padding: 4px 12px;
        border-radius: 9999px;
        font-size: 0.82rem;
        font-weight: 600;
    }
    .status-badge-cancelled {
        background-color: #4c0519;
        color: #fda4af;
        padding: 4px 12px;
        border-radius: 9999px;
        font-size: 0.82rem;
        font-weight: 600;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# ==============================================================================
# Helper Functions
# ==============================================================================
def api_request(method: str, path: str, token: str, **kwargs: Any) -> Any:
    headers = {"Authorization": f"Bearer {token}"}
    try:
        response = httpx.request(method, f"{API_URL}{path}", headers=headers, timeout=45, **kwargs)
        if response.is_error:
            try:
                detail = response.json().get("detail", response.text)
            except Exception:
                detail = response.text
            st.error(f"⚠️ Error {response.status_code}: {detail}")
            return None
        return response.json()
    except httpx.ConnectError:
        st.error(f"❌ Gagal terhubung ke API di `{API_URL}`. Pastikan backend FastAPI sedang berjalan.")
        return None
    except Exception as err:
        st.error(f"❌ Terjadi kesalahan koneksi: {err}")
        return None


def get_health_status() -> dict[str, Any]:
    try:
        resp = httpx.get(f"{API_URL}/readyz", timeout=3.0)
        if resp.status_code == 200:
            return resp.json()
    except Exception:
        pass
    return {"status": "offline", "ready": False}


def _fallback_lead_days_from_file() -> int:
    """Fallback cadangan membaca file kebijakan jika API/Agent sedang tidak aktif."""
    try:
        policy_file = Path(__file__).resolve().parent / "data" / "policies" / "annual-leave.md"
        if policy_file.exists():
            text = policy_file.read_text(encoding="utf-8").lower()
            match_h = re.search(r"\bh-(\d+)\b", text)
            if match_h:
                return int(match_h.group(1))
            kata_angka = {"satu": 1, "dua": 2, "tiga": 3, "empat": 4, "lima": 5, "tujuh": 7}
            for word, val in kata_angka.items():
                if f"{word} hari" in text:
                    return val
            match_num = re.search(r"(\d+)\s+hari", text)
            if match_num:
                return int(match_num.group(1))
    except Exception:
        pass
    return 3


@st.cache_data(ttl=120, show_spinner=False)
def _query_agent_for_lead_days(api_url: str, token: str, policy_mtime: float) -> int:
    """Menanyakan langsung ke AI Agent melalui endpoint /chat untuk menganalisis kebijakan resmi via RAG."""
    try:
        query_msg = (
            "Berapa hari minimal pengajuan cuti tahunan sebelum tanggal mulai menurut kebijakan HR? "
            "Sebutkan angka harinya secara jelas."
        )
        resp = httpx.post(
            f"{api_url}/chat",
            headers={"Authorization": f"Bearer {token}"},
            json={"message": query_msg},
            timeout=20.0,
        )
        if resp.status_code == 200:
            data = resp.json()
            answer = data.get("answer", "").lower()

            m_h = re.search(r"\bh-(\d+)\b", answer)
            if m_h:
                return int(m_h.group(1))

            kata_angka = {"satu": 1, "dua": 2, "tiga": 3, "empat": 4, "lima": 5, "tujuh": 7}
            for word, val in kata_angka.items():
                if f"{word} hari" in answer:
                    return val

            m_num = re.search(r"(\d+)\s+hari", answer)
            if m_num:
                return int(m_num.group(1))
    except Exception:
        pass

    return _fallback_lead_days_from_file()


def get_annual_leave_lead_days_from_policy(token: str = "") -> int:
    """Minta Agent AI membaca dan menganalisis kebijakan cuti tahunan via RAG (search_hr_policy).

    Fungsi ini memanfaatkan AI Agent untuk mengekstrak ketentuan batas minimal (H-x)
    langsung dari penelusuran dokumen kebijakan resmi perusahaan.
    """
    if not token:
        active_persona = st.session_state.get("active_persona") or {}
        token = active_persona.get("demo_token", "")

    policy_file = Path(__file__).resolve().parent / "data" / "policies" / "annual-leave.md"
    policy_mtime = policy_file.stat().st_mtime if policy_file.exists() else 0.0

    if token:
        return _query_agent_for_lead_days(API_URL, token, policy_mtime)

    return _fallback_lead_days_from_file()


def has_leave_intent(text: str) -> bool:
    """Mendeteksi apakah pesan pengguna atau dialog memuat niat pengajuan/permohonan cuti."""
    if not text:
        return False
    lower = text.lower()
    intent_keywords = [
        r"\b(?:mau|ingin|minta|request|ajukan|pengajuan|siapkan|buat|ambil|butuh|rencana)\s+.*cuti\b",
        r"\b(?:permohonan|pengajuan)\s+cuti\b",
        r"\bsiap(?:kan)?\s+cuti\b",
        r"\bcuti\b.*(?:ajukan|request|ambil|minta|butuh|mau|ingin|rencana)",
    ]
    return any(re.search(p, lower) for p in intent_keywords)


def get_min_start_date(leave_type: str, today: date, token: str = "") -> date:
    """Calculate the earliest allowable start date based on company policy.

    - Annual leave: Mengikuti analisis AI Agent terhadap dokumen kebijakan HR.
    - Sick / Parental leave: Can start from today (past dates are strictly blocked).
    """
    if leave_type != "annual":
        return today

    lead_days = get_annual_leave_lead_days_from_policy(token)
    # Hari kalender langsung (tidak mengabaikan akhir pekan)
    return today + timedelta(days=lead_days)


def render_leave_form() -> None:
    """Interactive leave application form with policy guardrails and live validations."""
    today = date.today()
    active_persona = st.session_state.get("active_persona") or {}
    token = active_persona.get("demo_token", "")

    leave_options = {
        "Cuti Tahunan": "annual",
        "Cuti Sakit": "sick",
        "Cuti Orang Tua": "parental",
    }

    leave_label = st.selectbox(
        "Pilih Jenis Cuti:",
        options=list(leave_options.keys()),
        key="dlg_leave_type_select",
        help="Pilih kategori cuti yang ingin diajukan sesuai hak Anda.",
    )
    leave_type = leave_options[leave_label]

    min_start = get_min_start_date(leave_type, today, token)

    # Sanitize session state if switching leave types changed the minimum date
    current_start = st.session_state.get("dlg_start_date")
    if current_start is not None and current_start < min_start:
        st.session_state["dlg_start_date"] = min_start

    col_d1, col_d2 = st.columns(2)
    with col_d1:
        start_val = st.session_state.get("dlg_start_date", min_start)
        start_date = st.date_input(
            "Tanggal Mulai:",
            value=start_val,
            min_value=min_start,
            key="dlg_start_date",
            help="Tanggal pertama cuti. Tidak bisa memilih sebelum tanggal minimal sesuai kebijakan.",
        )

    # Sanitize end_date relative to start_date
    current_end = st.session_state.get("dlg_end_date")
    if current_end is not None and current_end < start_date:
        st.session_state["dlg_end_date"] = start_date

    with col_d2:
        end_val = st.session_state.get("dlg_end_date", start_date)
        end_date = st.date_input(
            "Tanggal Selesai:",
            value=end_val,
            min_value=start_date,
            key="dlg_end_date",
            help="Tanggal terakhir cuti (minimal sama dengan tanggal mulai).",
        )

    # Calculate business days (Monday-Friday)
    work_days = sum(
        (start_date + timedelta(days=i)).weekday() < 5
        for i in range((end_date - start_date).days + 1)
    )

    # Policy guidelines banner
    if leave_type == "annual":
        lead_days = get_annual_leave_lead_days_from_policy(token)
        actual_lead = (start_date - today).days
        st.info(
            f"🤖 **Hasil Analisis AI Agent (HR-LEAVE-001):**\n"
            f"- AI Agent memverifikasi: Cuti tahunan wajib diajukan minimal **H-{lead_days}** ({lead_days} hari) sebelumnya.\n"
            f"- Jarak tanggal mulai pengajuan yang Anda pilih: **{actual_lead} hari** ke depan.\n"
            f"- Jatah cuti tahunan: 12 hari kerja/tahun kalender."
        )
    elif leave_type == "sick":
        if work_days > 2:
            st.warning(
                f"⚠️ **Kebijakan Cuti Sakit (HR-LEAVE-002):**\n"
                f"- Permohonan diajukan untuk **{work_days} hari kerja**.\n"
                f"- Cuti sakit lebih dari **2 hari kerja berturut-turut** mewajibkan surat keterangan dokter "
                f"yang diserahkan langsung melalui portal HR (bukan via chat asisten)."
            )
        else:
            st.info(
                "📌 **Kebijakan Cuti Sakit (HR-LEAVE-002):**\n"
                "- Harap beri tahu manajer sesegera mungkin.\n"
                "- Kerahasiaan medis terjamin, asisten tidak mencatat diagnosis detail."
            )
    elif leave_type == "parental":
        st.info(
            "📌 **Kebijakan Cuti Orang Tua (HR-LEAVE-003):**\n"
            "- Berlaku bagi pegawai tetap dengan masa kerja minimal 6 bulan.\n"
            "- Permohonan akan diverifikasi lebih lanjut oleh tim HR."
        )

    reason = st.text_area(
        "Alasan / Keterangan Pengajuan (opsional):",
        placeholder="Contoh: Keperluan keluarga mendesak / Pemulihan kesehatan",
        max_chars=300,
        key="dlg_reason_text",
    )

    if work_days == 0:
        st.error("⚠️ Rentang tanggal yang dipilih tidak memiliki hari kerja (hanya akhir pekan). Silakan pilih tanggal kerja.")
    else:
        st.success(f"🗓️ Total Durasi: **{work_days} hari kerja** (tidak termasuk Sabtu & Minggu).")

    col_btn_sub, col_btn_can = st.columns([1.3, 1])
    with col_btn_sub:
        can_submit = (work_days > 0)
        if st.button("🚀 Siapkan Permohonan Cuti", type="primary", use_container_width=True, disabled=not can_submit):
            reason_clean = reason.strip() if reason else ""
            reason_param = f" dengan alasan: {reason_clean}" if reason_clean else ""
            prompt = f"Siapkan {leave_label.lower()} ({leave_type}) dari {start_date.isoformat()} sampai {end_date.isoformat()}{reason_param}"
            st.session_state["prompt_input"] = prompt
            st.session_state["show_leave_modal"] = False
            st.rerun()

    with col_btn_can:
        if st.button("Batal", use_container_width=True):
            st.session_state["show_leave_modal"] = False
            st.rerun()


if hasattr(st, "dialog"):
    @st.dialog("📝 Formulir Pengajuan Cuti", width="medium")
    def leave_dialog():
        render_leave_form()
else:
    def leave_dialog():
        st.session_state["show_leave_modal"] = True


# Load persona catalog from demo_personas.json
personas_catalog = load_personas(Path(__file__).with_name("demo_personas.json"))

# ==============================================================================
# Session & Authentication State Management
# ==============================================================================
if "authenticated" not in st.session_state:
    st.session_state["authenticated"] = False
if "active_persona" not in st.session_state:
    st.session_state["active_persona"] = None
if "chat_history" not in st.session_state:
    st.session_state["chat_history"] = []
if "confirmed_proposals" not in st.session_state:
    st.session_state["confirmed_proposals"] = set()

# ==============================================================================
# VIEW 1: ENTERPRISE LOGIN PORTAL (Displayed when not logged in)
# ==============================================================================
if not st.session_state["authenticated"]:
    col_hero_l, col_hero_m, col_hero_r = st.columns([2.2, 1.2, 2.2])
    with col_hero_m:
        if os.path.exists(GUNUNGAN_LOGO):
            st.image(GUNUNGAN_LOGO, width=440)

    st.markdown(
        """
        <div class="login-hero" style="padding-top: 0.2rem;">
            <span class="login-badge">Portal Masuk Terintegrasi</span>
            <h1 style="color: #38bdf8; font-size: 2.2rem; font-weight: 800; margin-bottom: 0.2rem; margin-top: 0.2rem;">
                NUSANTARA DIGITAL
            </h1>
            <h3 style="color: #f8fafc; font-weight: 500; font-size: 1.2rem; margin-top: 0;">
                Asisten Kebijakan HR & Permohonan Cuti bersama <b>Miyo</b>
            </h3>
            <p style="color: #94a3b8; font-size: 0.95rem; max-width: 620px; margin: 0.6rem auto 1.5rem auto;">
                Sistem layanan mandiri karyawan berbasis AI dengan otentikasi identitas, isolasi data pribadi, dan validasi kebijakan resmi terverifikasi.
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    login_tab1, login_tab2 = st.tabs(["👥 Pilih Persona Demo (Akses Cepat)", "🔑 Masuk dengan Bearer Token Manual"])

    # Method 1: Interactive Persona Cards
    with login_tab1:
        st.markdown("Pilih salah satu profil karyawan demo untuk menguji skenario:")
        cols = st.columns(len(personas_catalog))

        # Metadata display icons & roles
        persona_meta = {
            "EMP-001": {"avatar": "👩‍💼", "badge": "Pegawai Reguler", "quota": "Saldo: 8 Hari Cuti Tahunan"},
            "EMP-002": {"avatar": "👨‍💼", "badge": "Pegawai Reguler", "quota": "Saldo: 3 Hari Cuti Tahunan"},
            "ADM-001": {"avatar": "🛡️", "badge": "Monitoring Admin", "quota": "Akses: Audit, Metrik, & SLI/SLA"},
        }

        for idx, p in enumerate(personas_catalog):
            emp_id = p["employee_id"]
            meta = persona_meta.get(emp_id, {"avatar": "👤", "badge": "Karyawan", "quota": ""})

            with cols[idx]:
                st.markdown(
                    f"""
                    <div class="persona-login-card">
                        <div>
                            <div class="persona-avatar">{meta['avatar']}</div>
                            <div class="persona-login-name">{p['label']}</div>
                            <div class="persona-login-role">ID: <code>{emp_id}</code> · {meta['badge']}</div>
                            <div style="background-color: #334155; color: #f8fafc; padding: 3px 8px; border-radius: 6px; font-size: 0.78rem; font-weight: 600; margin-bottom: 8px;">
                                {meta['quota']}
                            </div>
                            <div class="persona-login-desc">{p['scenario']}</div>
                        </div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
                if st.button(f"🚀 Masuk sebagai {p['label'].split('—')[0].strip()}", key=f"login_btn_{emp_id}", use_container_width=True, type="primary"):
                    st.session_state["authenticated"] = True
                    st.session_state["active_persona"] = p
                    select_persona(st.session_state, p)
                    st.session_state["chat_history"] = []
                    st.session_state["confirmed_proposals"] = set()
                    st.rerun()

    # Method 2: Manual Bearer Token Input
    with login_tab2:
        st.markdown("Masukkan token otentikasi Bearer Anda untuk login manual:")
        with st.form("manual_token_form"):
            token_input = st.text_input(
                "Bearer Token:",
                type="password",
                placeholder="contoh: token-alya atau token-admin",
                help="Gunakan token demo sintetis yang terdaftar di sistem.",
            )
            submit_token = st.form_submit_button("🔓 Masuk ke Sistem", type="primary", use_container_width=True)

            if submit_token:
                cleaned_token = token_input.strip()
                if not cleaned_token:
                    st.error("Token otentikasi tidak boleh kosong.")
                else:
                    # Match against persona catalog
                    matched_persona = next((p for p in personas_catalog if p["demo_token"] == cleaned_token), None)
                    if matched_persona:
                        st.session_state["authenticated"] = True
                        st.session_state["active_persona"] = matched_persona
                        select_persona(st.session_state, matched_persona)
                        st.session_state["chat_history"] = []
                        st.session_state["confirmed_proposals"] = set()
                        st.success(f"Berhasil masuk sebagai {matched_persona['label']}!")
                        time.sleep(0.5)
                        st.rerun()
                    else:
                        st.error("❌ Token otentikasi tidak dikenali atau tidak valid. Silakan gunakan token demo yang tersedia.")

    st.markdown("---")
    # Health status footer
    h = get_health_status()
    if h.get("ready"):
        st.caption("🟢 Backend API & Database Neon Serverless Postgres Siap.")
    else:
        st.caption(f"🟡 Status Backend: {h.get('status', 'degraded')}")

    # Stop rendering the rest of the application until logged in
    st.stop()


# ==============================================================================
# VIEW 2: AUTHENTICATED DASHBOARD (Displayed after successful login)
# ==============================================================================
persona = st.session_state["active_persona"]
token = persona["demo_token"]
is_admin = "ADM" in persona["employee_id"]

# Sidebar: User Profile & Actions
with st.sidebar:
    col_sb_logo, col_sb_txt = st.columns([1, 2.5])
    with col_sb_logo:
        if os.path.exists(MIYO_LOGO):
            st.image(MIYO_LOGO, width=65)
        else:
            st.title("🧭")
    with col_sb_txt:
        st.markdown("<h3 style='margin:0; padding-top:6px; color:#38bdf8;'>Asisten Miyo</h3>", unsafe_allow_html=True)
        st.caption("Nusantara Digital HR")
    st.markdown("---")

    # Active Logged-in User Profile Card
    st.markdown(
        f"""
        <div class="user-profile-card">
            <div style="font-size: 0.75rem; text-transform: uppercase; color: #94a3b8; font-weight: 700; margin-bottom: 4px;">Akun Aktif</div>
            <div class="user-profile-name">{'🛡️' if is_admin else '👤'} {persona['label']}</div>
            <div class="user-profile-role">ID: <code>{persona['employee_id']}</code> · Role: <b>{'Monitoring Admin' if is_admin else 'Pegawai'}</b></div>
            <div class="user-profile-scenario">{persona['scenario']}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # Logout / Switch Persona Button
    if st.button("🚪 Keluar / Ganti Akun", use_container_width=True, type="secondary"):
        st.session_state["authenticated"] = False
        st.session_state["active_persona"] = None
        st.session_state["chat_history"] = []
        st.session_state["confirmed_proposals"] = set()
        st.rerun()

    st.markdown("---")

    # Leave Request Action for Employees
    if not is_admin:
        st.markdown("##### 📅 Formulir Cuti:")
        if st.button("📝 Ajukan Permohonan Cuti", key="btn_open_leave_dialog", use_container_width=True, type="primary"):
            if hasattr(st, "dialog"):
                leave_dialog()
            else:
                st.session_state["show_leave_modal"] = True
                st.rerun()
        st.markdown("---")

    # Quick Suggestion Prompts
    st.markdown("##### 💡 Rekomendasi Pertanyaan:")
    quick_queries = [
        "Berapa jatah cuti tahunan?",
        "Berapa sisa saldo cuti saya?",
        "Kapan surat dokter diperlukan?",
        "Boleh WFH berapa hari per minggu?",
   ]

    for q in quick_queries:
        if st.button(q, key=f"quick_{q}", use_container_width=True):
            st.session_state["prompt_input"] = q

    st.markdown("---")
    if st.button("🧹 Bersihkan Percakapan", use_container_width=True):
        st.session_state["chat_history"] = []
        st.session_state["confirmed_proposals"] = set()
        st.rerun()

    # Brand Footer in Sidebar
    if os.path.exists(GUNUNGAN_LOGO):
        st.image(GUNUNGAN_LOGO, use_container_width=True)
        st.markdown("<div style='text-align: center; font-size: 0.75rem; color: #64748b; margin-top: -6px; margin-bottom: 8px;'>PT Nusantara Digital</div>", unsafe_allow_html=True)

    # Health Indicator in Sidebar Footer
    health = get_health_status()
    if health.get("ready"):
        st.success("🟢 Terhubung ke Neon Cloud DB")
    else:
        st.warning(f"🟡 Status Sistem: {health.get('status', 'degraded')}")

# Main Layout: Header with Nusantara Digital Gunungan & Miyo Mascot
col_hdr_logo, col_hdr_content = st.columns([0.8, 6.2])
with col_hdr_logo:
    if os.path.exists(GUNUNGAN_LOGO):
        st.image(GUNUNGAN_LOGO, width=240)
with col_hdr_content:
    st.markdown("<h2 style='margin-bottom:2px; color:#f8fafc;'>Asisten Kebijakan HR dan Cuti</h2>", unsafe_allow_html=True)
    st.markdown(
        "<div style='color:#38bdf8; font-weight:600; font-size:1.05rem; margin-bottom:4px;'>"
        "PT Nusantara Digital · AI Partner: Miyo"
        "</div>",
        unsafe_allow_html=True,
    )
    st.caption("Pusat layanan mandiri kebijakan, penelusuran hak pegawai, dan pengajuan cuti bergaransi keamanan.")
st.markdown("---")

# Dynamic Tabs based on Role: Admins see Monitoring, Employees see Self-Service
if is_admin:
    tab_chat, tab_requests, tab_monitoring = st.tabs(
        ["💬 Percakapan Interaktif", "📋 Permintaan Cuti Saya", "📊 Monitoring Operasional"]
    )
else:
    tab_chat, tab_requests = st.tabs(
        ["💬 Percakapan Interaktif", "📋 Permintaan Cuti Saya"]
    )
    tab_monitoring = None

# ------------------------------------------------------------------------------
# TAB 1: Conversational Chat
# ------------------------------------------------------------------------------
with tab_chat:
    # Fallback container for leave form if running on older Streamlit without native modal dialog
    if not hasattr(st, "dialog") and st.session_state.get("show_leave_modal", False):
        with st.container():
            st.markdown("### 📝 Formulir Pengajuan Cuti")
            render_leave_form()
            st.markdown("---")

    # Render past conversation history
    assistant_avatar = MIYO_LOGO if os.path.exists(MIYO_LOGO) else "🧭"
    for idx, entry in enumerate(st.session_state["chat_history"]):
        with st.chat_message(entry["role"], avatar="👤" if entry["role"] == "user" else assistant_avatar):
            st.markdown(entry["content"])

            # If citations exist
            if entry.get("citations"):
                with st.expander(f"📚 Sumber Kebijakan Terverifikasi ({len(entry['citations'])})", expanded=False):
                    for cite in entry["citations"]:
                        st.markdown(
                            f"""
                            <div class="citation-card">
                                <div class="citation-header">📌 [{cite['document_id']}] {cite['title']} — {cite['section']}</div>
                                <div class="citation-body">"{cite['excerpt']}"</div>
                            </div>
                            """,
                            unsafe_allow_html=True,
                        )

            # If an action proposal is attached
            proposal = entry.get("action_proposal")
            if proposal:
                prop_id = proposal["proposal_id"]
                is_confirmed = prop_id in st.session_state["confirmed_proposals"]

                if is_confirmed:
                    st.success(f"✅ Permintaan `{prop_id}` telah dikonfirmasi dan berstatus `pending_manager_review`.")
                else:
                    st.markdown(
                        f"""
                        <div class="proposal-box">
                            <div class="proposal-title">📝 Proposal Permohonan Cuti (Menunggu Konfirmasi)</div>
                            <div class="proposal-detail"><b>Jenis Cuti:</b> {proposal['leave_type'].capitalize()}</div>
                            <div class="proposal-detail"><b>Rentang Tanggal:</b> {proposal['start_date']} s/d {proposal['end_date']} (<b>{proposal['business_days']} hari kerja</b>)</div>
                            <div class="proposal-detail"><b>Alasan:</b> {proposal.get('reason') or 'Tidak dicantumkan'}</div>
                            <div>
                                {''.join([f'<span class="validation-badge">✓ {v}</span>' for v in proposal.get('validation_summary', [])])}
                                <span class="expiry-tag">⏱️ Batas Konfirmasi: {proposal['expires_at'][:19].replace('T', ' ')} UTC</span>
                            </div>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )

                    col_btn1, col_btn2, col_btn3 = st.columns([1.2, 1.4, 2.5])
                    with col_btn1:
                        confirm_key = f"btn_confirm_{prop_id}"
                        if st.button("✅ Konfirmasi Pengajuan", key=confirm_key, type="primary"):
                            idem_key = f"idem_{prop_id}"
                            st.session_state.setdefault(idem_key, str(uuid.uuid4()))
                            with st.spinner("Mengonfirmasi dan mengunci request..."):
                                confirmed = api_request(
                                    "POST",
                                    API_PATHS["confirm"].format(proposal_id=prop_id),
                                    token,
                                    json={"idempotency_key": st.session_state[idem_key]},
                                )
                            if confirmed:
                                st.session_state["confirmed_proposals"].add(prop_id)
                                st.success(
                                    f"🎉 Permintaan cuti #{confirmed['request_id']} berhasil diajukan dengan status `{confirmed['status']}`."
                                )
                                time.sleep(1)
                                st.rerun()
                    with col_btn2:
                        if st.button("📅 Ubah via Formulir", key=f"btn_edit_prop_{prop_id}", type="secondary"):
                            if hasattr(st, "dialog"):
                                leave_dialog()
                            else:
                                st.session_state["show_leave_modal"] = True
                                st.rerun()

            # If dialogue expresses intent to request leave and proposal is not yet generated
            if entry["role"] == "assistant" and not is_admin and not proposal:
                prev_user_msg = (
                    st.session_state["chat_history"][idx - 1].get("content", "")
                    if idx > 0 and st.session_state["chat_history"][idx - 1].get("role") == "user"
                    else ""
                )
                if has_leave_intent(prev_user_msg) or has_leave_intent(entry.get("content", "")):
                    st.markdown(
                        """
                        <div style="background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%); border: 1px solid #0284c7; border-radius: 10px; padding: 12px 16px; margin-top: 10px; margin-bottom: 8px;">
                            <div style="font-weight: 700; color: #38bdf8; font-size: 0.95rem; margin-bottom: 2px;">
                                📅 Formulir Permohonan Cuti
                            </div>
                            <div style="font-size: 0.83rem; color: #cbd5e1;">
                                Ingin langsung mengajukan cuti? Klik tombol di bawah untuk memilih tanggal via kalender interaktif, atau Anda tetap dapat mengetik permohonan secara manual di kolom chat.
                            </div>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )
                    col_form_btn, _ = st.columns([1.5, 2.5])
                    with col_form_btn:
                        if st.button("📝 Formulir Ajukan Permohonan Cuti", key=f"btn_form_chat_{idx}", type="primary"):
                            if hasattr(st, "dialog"):
                                leave_dialog()
                            else:
                                st.session_state["show_leave_modal"] = True
                                st.rerun()

            # Technical details in collapsed expander
            if entry.get("trace_id"):
                with st.expander("🔍 Trace & Telemetry Audit", expanded=False):
                    trace_col1, trace_col2 = st.columns(2)
                    with trace_col1:
                        st.caption(f"**Outcome:** `{entry.get('outcome')}`")
                        st.caption(f"**Trace ID:** `{entry.get('trace_id')}`")
                    with trace_col2:
                        usage = entry.get("usage", {})
                        st.caption(f"**Latency:** {usage.get('latency_ms', 0)} ms")
                        st.caption(f"**Tokens:** {usage.get('input_tokens', 0)} in / {usage.get('output_tokens', 0)} out")
                    if entry.get("tool_calls"):
                        st.write("**Tool Calls:**")
                        for tc in entry["tool_calls"]:
                            st.caption(f"- `{tc.get('name')}` · Status: `{tc.get('status')}` ({tc.get('duration_ms', 0)} ms)")

    # Chat Input Box
    default_prompt = st.session_state.pop("prompt_input", "")
    user_input = st.chat_input("Tanyakan kebijakan, aturan kerja, atau ajukan cuti Anda...")

    # If triggered via quick button or direct chat input
    prompt_to_send = user_input or (default_prompt if default_prompt else None)

    if prompt_to_send:
        # 1. Display User Message
        st.session_state["chat_history"].append({"role": "user", "content": prompt_to_send})
        with st.chat_message("user", avatar="👤"):
            st.markdown(prompt_to_send)

        # 2. Call FastAPI Backend
        assistant_avatar = MIYO_LOGO if os.path.exists(MIYO_LOGO) else "🧭"
        with st.chat_message("assistant", avatar=assistant_avatar):
            with st.spinner("Miyo sedang menelusuri kebijakan resmi dan memverifikasi data..."):
                result = api_request("POST", API_PATHS["chat"], token, json={"message": prompt_to_send})

            if result:
                st.markdown(result["answer"])

                # Store assistant response in history
                st.session_state["chat_history"].append(
                    {
                        "role": "assistant",
                        "content": result["answer"],
                        "outcome": result.get("outcome"),
                        "citations": result.get("citations", []),
                        "action_proposal": result.get("action_proposal"),
                        "tool_calls": result.get("tool_calls", []),
                        "trace_id": result.get("trace_id"),
                        "usage": result.get("usage", {}),
                    }
                )
                st.rerun()

# ------------------------------------------------------------------------------
# TAB 2: Leave Requests Tracker
# ------------------------------------------------------------------------------
with tab_requests:
    st.subheader(f"Daftar Permohonan Cuti: {persona['label']}")
    st.caption("Daftar seluruh pengajuan cuti aktif dan historis milik identitas Anda.")

    col_sync, col_create, _ = st.columns([1, 1.3, 3])
    with col_sync:
        refresh_btn = st.button("🔄 Segarkan Data", use_container_width=True)
    with col_create:
        if not is_admin:
            if st.button("📝 Buat Pengajuan Baru", key="btn_open_leave_tab2", use_container_width=True, type="primary"):
                if hasattr(st, "dialog"):
                    leave_dialog()
                else:
                    st.session_state["show_leave_modal"] = True
                    st.rerun()

    leave_data = api_request("GET", API_PATHS["my_requests"], token)

    if leave_data is not None:
        if not leave_data:
            st.info("Belum ada permohonan cuti yang diajukan oleh akun ini.")
        else:
            # Summary Metrics
            total_days = sum(item.get("business_days", 0) for item in leave_data)
            pending_count = sum(1 for item in leave_data if item.get("status") == "pending_manager_review")

            m_col1, m_col2, m_col3 = st.columns(3)
            m_col1.metric("Total Permohonan", len(leave_data))
            m_col2.metric("Menunggu Review", pending_count)
            m_col3.metric("Total Hari Kerja", f"{total_days} Hari")

            st.markdown("---")

            # Render each request as a clean card
            for req in leave_data:
                status_raw = req.get("status", "")
                if status_raw == "pending_manager_review":
                    badge_html = '<span class="status-badge-pending">⏳ Menunggu Review Manajer</span>'
                elif status_raw == "approved":
                    badge_html = '<span class="status-badge-approved">✓ Disetujui</span>'
                else:
                    badge_html = f'<span class="status-badge-cancelled">{status_raw.capitalize()}</span>'

                with st.container():
                    st.markdown(
                        f"""
                        <div style="background-color: #1e293b; border: 1px solid #334155; border-radius: 10px; padding: 14px 18px; margin-bottom: 12px;">
                            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
                                <div style="font-weight: 700; font-size: 1.05rem; color: #f8fafc;">
                                    ID: <code>{req.get('request_id')}</code> — Cuti {req.get('leave_type', '').capitalize()}
                                </div>
                                <div>{badge_html}</div>
                            </div>
                            <div style="color: #cbd5e1; font-size: 0.92rem;">
                                📅 <b>Periode:</b> {req.get('start_date')} s/d {req.get('end_date')} (<b>{req.get('business_days')} hari kerja</b>)
                            </div>
                            <div style="color: #94a3b8; font-size: 0.8rem; margin-top: 6px;">
                                Diajukan pada: {req.get('created_at', '')[:19].replace('T', ' ')} UTC
                            </div>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )

# ------------------------------------------------------------------------------
# TAB 3: Operational Monitoring & Audit (Admin Only)
# ------------------------------------------------------------------------------
if is_admin and tab_monitoring is not None:
    with tab_monitoring:
        st.subheader("Ringkasan Telemetry & Audit Operasional")
        st.caption("Metrik agregat, monitoring ambang batas SLI/SLA, dan alert tindakan operasional.")

        col_mon_sync, _ = st.columns([1, 4])
        with col_mon_sync:
            if st.button("🔄 Segarkan Metrik", key="btn_refresh_mon", use_container_width=True):
                st.rerun()

        summary = api_request("GET", API_PATHS["monitoring_summary"], token)
        alerts = api_request("GET", API_PATHS["monitoring_alerts"], token)

        if summary:
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Total Percakapan", summary.get("run_count", 0))
            err_rate = float(summary.get("error_rate", 0.0))
            c2.metric("Tingkat Error", f"{err_rate:.1%}")
            p95 = float(summary.get("p95_latency_ms", 0.0))
            c3.metric("p95 Latency", f"{int(p95)} ms")
            c4.metric("Total Tool Calls", summary.get("tool_calls", 0))

            st.markdown("---")

        if alerts is not None:
            st.subheader("🚨 Status Aturan Alert Operasional")
            if not alerts:
                st.success("✅ Seluruh metrik operasional berada di bawah ambang batas normal. Tidak ada alert aktif.")
            else:
                for alert in alerts:
                    st.error(
                        f"""
                        **[ALERT AKTIF] Aturan: `{alert.get('rule_id')}`**
                        - **Metrik:** `{alert.get('metric')}` (Nilai saat ini: `{alert.get('current_value')}`, Ambang Batas: `{alert.get('threshold')}`)
                        - **Penanggung Jawab:** `{alert.get('owner')}`
                        - **Prosedur Respons:** {alert.get('response')}
                        """
                    )
