"""Sidebar component displaying active user profile, vertical menu bar tabs, theme toggle, and health status."""
from __future__ import annotations

import base64
import os

import streamlit as st

from ui.api_client import get_health_status
from ui.config import GUNUNGAN_LOGO, MIYO_LOGO
from ui.icons import svg_icon
from ui.leave_form import leave_dialog


def render_sidebar() -> tuple[str, dict, bool, bool, str]:
    """Render sidebar navigation, user profile, theme toggle, and health status."""
    persona = st.session_state["active_persona"]
    token = persona["demo_token"]
    user_role = persona.get("role") or (
        "monitoring_admin" if "ADM" in persona["employee_id"] else ("manager" if "MGR" in persona["employee_id"] else "employee")
    )
    is_admin = user_role == "monitoring_admin"
    is_manager = user_role in ("manager", "monitoring_admin")
    role_badge = "MONITORING ADMIN" if is_admin else ("MANAGER" if user_role == "manager" else "PEGAWAI")

    # Generate initials for avatar
    initials = "".join([part[0] for part in persona["label"].split("—")[0].split()[:2]]).upper()

    with st.sidebar:
        # Header Brand in Sidebar (Logo Nusantara Digital di pojok kiri atas)
        col_sb_logo, col_sb_txt, col_sb_theme = st.columns([1, 2.3, 0.9])
        with col_sb_logo:
            if os.path.exists(GUNUNGAN_LOGO):
                st.image(GUNUNGAN_LOGO, width=48)
        with col_sb_txt:
            st.markdown(
                "<h3 style='margin:0; padding-top:2px; color: var(--text-primary); font-weight:700; font-size:1.02rem; letter-spacing:-0.02em;'>Nusantara Digital</h3>",
                unsafe_allow_html=True,
            )
            st.caption("Asisten HR Miyo")
        with col_sb_theme:
            # Theme Toggle: Icon bulan/matahari
            cur_theme = st.session_state.get("ui_theme", "dark")
            theme_icon = ":material/light_mode:" if cur_theme == "dark" else ":material/dark_mode:"
            theme_help = "Beralih ke Mode Terang" if cur_theme == "dark" else "Beralih ke Mode Gelap"
            if st.button("", icon=theme_icon, key="btn_theme_toggle_sb", help=theme_help, use_container_width=True):
                st.session_state["ui_theme"] = "light" if cur_theme == "dark" else "dark"
                st.rerun()

        st.markdown("<div style='height: 6px;'></div>", unsafe_allow_html=True)

        # Active User Identity Card (Claude Aesthetic)
        st.markdown(
            f"""
            <div class="user-identity-card">
                <div class="user-identity-initial">{initials}</div>
                <div style="flex: 1; min-width: 0;">
                    <div style="font-size: 0.92rem; font-weight: 600; color: var(--text-primary); white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">
                        {persona['label'].split('—')[0].strip()}
                    </div>
                    <div style="font-size: 0.75rem; color: var(--text-muted); display: flex; align-items: center; gap: 6px; margin-top: 2px;">
                        <span style="font-family: var(--font-mono); color: var(--accent-orange);">{persona['employee_id']}</span>
                        <span>•</span>
                        <span>{role_badge}</span>
                    </div>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        # Menu Bar: Sidebar Vertical Navigation Tabs with Highlight
        st.markdown(
            "<div style='font-size: 0.78rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.08em; color: var(--accent-orange); margin-bottom: 8px;'>Menu Bar</div>",
            unsafe_allow_html=True,
        )

        nav_options = [
            "Asisten Kebijakan",
            "Permohonan Cuti Saya",
            "Kalender Cuti",
        ]
        if is_manager:
            nav_options.append("Persetujuan Tim")
        if is_admin:
            nav_options.append("Monitoring Operasional")

        saved_tab = st.session_state.get("nav_active_tab")
        default_idx = nav_options.index(saved_tab) if saved_tab in nav_options else 0

        active_tab = st.radio(
            "Pilih Menu Bar",
            options=nav_options,
            index=default_idx,
            key="nav_active_tab_radio",
            label_visibility="collapsed",
        )
        st.session_state["nav_active_tab"] = active_tab

        st.markdown("<div style='height: 12px;'></div>", unsafe_allow_html=True)

        # Leave Request Action for Employees & Managers
        if not is_admin:
            if st.button("Formulir Pengajuan Cuti", key="btn_open_leave_dialog", use_container_width=True, type="primary"):
                if hasattr(st, "dialog"):
                    leave_dialog()
                else:
                    st.session_state["show_leave_modal"] = True
                    st.rerun()

        # Switch Persona / Logout Button
        if st.button("Ganti Sesi Pengguna", use_container_width=True, type="secondary"):
            st.session_state["authenticated"] = False
            st.session_state["active_persona"] = None
            st.session_state["chat_history"] = []
            st.session_state["confirmed_proposals"] = set()
            st.session_state.pop("pending_stepup_user", None)
            st.session_state.pop("nav_active_tab", None)
            st.rerun()

        st.markdown("<div style='height: 24px;'></div>", unsafe_allow_html=True)

        # Pojok Kiri Bawah: Logo Nusantara Digital, Nama Nusantara Digital, dan Sistem & Database Siap
        health = get_health_status()
        status_dot_class = "status-dot-active" if health.get("ready") else "status-dot-pending"
        status_text = "Sistem & Database Siap" if health.get("ready") else f"Degraded: {health.get('status', 'offline')}"

        gunungan_b64 = ""
        if os.path.exists(GUNUNGAN_LOGO):
            try:
                with open(GUNUNGAN_LOGO, "rb") as f:
                    gunungan_b64 = base64.b64encode(f.read()).decode("ascii")
            except Exception:
                gunungan_b64 = ""

        logo_html = (
            f'<img src="data:image/png;base64,{gunungan_b64}" style="width: 26px; height: 26px; object-fit: contain;" />'
            if gunungan_b64
            else '<span style="font-weight: 800; color: var(--accent-orange); font-size: 0.82rem; font-family: var(--font-mono);">ND</span>'
        )

        st.markdown(
            f"""
            <div style="background-color: var(--bg-surface-elevated); border: 1px solid var(--border-subtle); border-radius: 10px; padding: 10px 12px; margin-top: auto;">
                <div style="display: flex; align-items: center; gap: 10px; margin-bottom: 6px;">
                    <div style="width: 28px; height: 28px; border-radius: 6px; overflow: hidden; background: transparent; display: flex; align-items: center; justify-content: center;">
                        {logo_html}
                    </div>
                    <div>
                        <div style="font-size: 0.84rem; font-weight: 700; color: var(--text-primary); letter-spacing: -0.01em;">Nusantara Digital</div>
                        <div style="font-size: 0.72rem; color: var(--text-muted);">Internal HR Portal</div>
                    </div>
                </div>
                <div style="display: flex; align-items: center; gap: 8px; font-size: 0.76rem; border-top: 1px solid var(--border-subtle); padding-top: 6px;">
                    <span class="status-dot {status_dot_class}"></span>
                    <span style="color: var(--text-secondary); font-weight: 500;">{status_text}</span>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    return token, persona, is_manager, is_admin, active_tab
