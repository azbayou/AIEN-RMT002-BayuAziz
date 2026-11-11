"""Sidebar component displaying active user profile, quick prompts, theme toggle, and health status."""
from __future__ import annotations

import os

import streamlit as st

from ui.api_client import get_health_status
from ui.config import GUNUNGAN_LOGO, MIYO_LOGO
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

    with st.sidebar:
        col_sb_logo, col_sb_txt = st.columns([1, 2.5])
        with col_sb_logo:
            if os.path.exists(MIYO_LOGO):
                st.image(MIYO_LOGO, width=65)
        with col_sb_txt:
            st.markdown("<h3 style='margin:0; padding-top:6px; color: var(--accent-sky); font-weight:700;'>Miyo Assistant</h3>", unsafe_allow_html=True)
            st.caption("PT Nusantara Digital")
        st.markdown("---")

        # Theme toggle trigger
        cur_theme = st.session_state.get("ui_theme", "dark")
        new_theme_label = "Mode Terang" if cur_theme == "dark" else "Mode Gelap"
        if st.button(new_theme_label, key="btn_theme_toggle_sb", use_container_width=True):
            st.session_state["ui_theme"] = "light" if cur_theme == "dark" else "dark"
            st.rerun()

        # Active User Profile Card
        st.markdown(
            f"""
            <div class="user-profile-card">
                <div style="font-size: 0.72rem; text-transform: uppercase; letter-spacing: 0.08em; color: var(--text-muted); font-weight: 700; margin-bottom: 4px;">Sesi Pengguna Aktif</div>
                <div class="user-profile-name">{persona['label']}</div>
                <div class="user-profile-role">ID: <code>{persona['employee_id']}</code> · Role: <b>{role_badge}</b></div>
                <div class="user-profile-scenario">{persona.get('scenario', '-')}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        # Sidebar Navigation Tabs (Moved from main top tabs)
        st.markdown("##### Menu Navigasi")
        nav_options = [
            "Asisten Kebijakan",
            "Permohonan Cuti Saya",
            "Kalender Cuti",
        ]
        if is_manager:
            nav_options.append("Persetujuan Tim")
        if is_admin:
            nav_options.append("Monitoring Operasional")

        # Synchronize active nav selection with session state
        saved_tab = st.session_state.get("nav_active_tab")
        default_idx = nav_options.index(saved_tab) if saved_tab in nav_options else 0

        active_tab = st.radio(
            "Pilih Menu Navigasi",
            options=nav_options,
            index=default_idx,
            key="nav_active_tab_radio",
            label_visibility="collapsed",
        )
        st.session_state["nav_active_tab"] = active_tab

        st.markdown("---")

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

        st.markdown("---")

        # Brand Footer in Sidebar
        if os.path.exists(GUNUNGAN_LOGO):
            st.image(GUNUNGAN_LOGO, use_container_width=True)
            st.markdown("<div style='text-align: center; font-size: 0.75rem; color: var(--text-muted); margin-top: -6px; margin-bottom: 8px;'>PT Nusantara Digital</div>", unsafe_allow_html=True)

        # Health Indicator in Sidebar Footer
        health = get_health_status()
        if health.get("ready"):
            st.success("[SISTEM AKTIF] Database & Layanan Siap")
        else:
            st.warning(f"[STATUS DEGRADED] Layanan: {health.get('status', 'offline')}")

    return token, persona, is_manager, is_admin, active_tab
