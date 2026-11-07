"""Interactive Enterprise Streamlit UI for Miyo HR Policy & Leave Assistant."""
from __future__ import annotations

import os
import threading
import time
import uuid
from datetime import datetime, timezone
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
# Page Setup & Custom CSS Styling
# ==============================================================================
st.set_page_config(
    page_title="Miyo — Asisten HR Nusantara Digital",
    page_icon="🧭",
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
    
    /* Persona Card */
    .persona-card {
        background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%);
        border: 1px solid #334155;
        border-radius: 12px;
        padding: 14px 16px;
        margin-bottom: 15px;
        color: #f8fafc;
    }
    .persona-name {
        font-weight: 700;
        font-size: 1.1rem;
        color: #38bdf8;
    }
    .persona-role {
        font-size: 0.82rem;
        color: #94a3b8;
        margin-bottom: 6px;
    }
    .persona-scenario {
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


# ==============================================================================
# Persona Selection & Session Initialization
# ==============================================================================
personas_catalog = load_personas(Path(__file__).with_name("demo_personas.json"))

# Initialize state
if "chat_history" not in st.session_state:
    st.session_state["chat_history"] = []
if "pending_proposals" not in st.session_state:
    st.session_state["pending_proposals"] = {}
if "confirmed_proposals" not in st.session_state:
    st.session_state["confirmed_proposals"] = set()

# Sidebar: Persona switcher & Identity management
with st.sidebar:
    st.title("🧭 Asisten Miyo")
    st.caption("AI-Powered HR Policy & Action Assistant")
    st.markdown("---")

    persona = st.selectbox(
        "Pilih Persona Demo:",
        personas_catalog,
        format_func=lambda item: f"{item['label']} ({item['employee_id']})",
    )

    # Sync persona state with ui_contract
    prev_emp = st.session_state.get("active_employee_id")
    select_persona(st.session_state, persona)
    if prev_emp != persona["employee_id"]:
        st.session_state["chat_history"] = []
        st.session_state["pending_proposals"] = {}
        st.session_state["confirmed_proposals"] = set()

    token = persona["demo_token"]

    # Persona Information Card
    st.markdown(
        f"""
        <div class="persona-card">
            <div class="persona-name">👤 {persona['label']}</div>
            <div class="persona-role">ID: <code>{persona['employee_id']}</code> · Role: { 'Admin' if 'ADM' in persona['employee_id'] else 'Pegawai' }</div>
            <div class="persona-scenario">{persona['scenario']}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # Quick Suggestion Prompts
    st.markdown("##### 💡 Rekomendasi Pertanyaan:")
    quick_queries = [
        "Berapa jatah cuti tahunan?",
        "Berapa sisa saldo cuti saya?",
        "Kapan surat dokter diperlukan?",
        "Boleh WFH berapa hari per minggu?",
        "Siapkan cuti tahunan 2026-11-23 sampai 2026-11-24",
    ]

    for q in quick_queries:
        if st.button(q, key=f"quick_{q}", use_container_width=True):
            st.session_state["prompt_input"] = q

    st.markdown("---")
    if st.button("🧹 Bersihkan Percakapan", use_container_width=True):
        st.session_state["chat_history"] = []
        st.session_state["pending_proposals"] = {}
        st.rerun()

    # Health Indicator in Sidebar Footer
    health = get_health_status()
    if health.get("ready"):
        st.success("🟢 Sistem Siap (pgvector & DB Terhubung)")
    else:
        st.warning(f"🟡 Status Sistem: {health.get('status', 'degraded')}")

# ==============================================================================
# Main Layout: Header & Tabs
# ==============================================================================
st.title("Asisten Kebijakan HR dan Cuti")
st.caption("Pusat layanan mandiri kebijakan, penelusuran hak pegawai, dan pengajuan cuti bergaransi keamanan.")

tab_chat, tab_requests, tab_monitoring = st.tabs(
    ["💬 Percakapan Interaktif", "📋 Permintaan Cuti Saya", "📊 Monitoring Operasional"]
)

# ------------------------------------------------------------------------------
# TAB 1: Conversational Chat
# ------------------------------------------------------------------------------
with tab_chat:
    # Render past conversation history
    for entry in st.session_state["chat_history"]:
        with st.chat_message(entry["role"], avatar="👤" if entry["role"] == "user" else "🧭"):
            st.markdown(entry["content"])

            # If there are citations attached
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

                    col_btn1, col_btn2 = st.columns([1, 4])
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
        with st.chat_message("assistant", avatar="🧭"):
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

    col_sync, _ = st.columns([1, 4])
    with col_sync:
        refresh_btn = st.button("🔄 Segarkan Data", use_container_width=True)

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
with tab_monitoring:
    is_admin = "ADM" in persona["employee_id"]

    if not is_admin:
        st.warning("🔒 **Akses Dibatasi:** Tab monitoring hanya dapat diakses oleh persona `Monitoring Admin`.")
        st.info("Pilih persona `Monitoring admin (ADM-001)` pada menu dropdown di sidebar kiri untuk membuka tab ini.")
    else:
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
