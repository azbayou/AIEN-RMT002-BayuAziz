"""Enterprise Streamlit Sub-App Orchestrator for Miyo HR Assistant."""
from __future__ import annotations

import os
from pathlib import Path

import streamlit as st

from ui.api_client import ensure_api_running
from ui.config import GUNUNGAN_LOGO, init_page_and_theme
from ui.session_selector import render_session_selector
from ui.sidebar import render_sidebar
from ui.tab_approvals import render_tab_team_approvals
from ui.tab_calendar import render_tab_calendar
from ui.tab_chat import render_tab_chat
from ui.tab_monitoring import render_tab_monitoring
from ui.tab_requests import render_tab_my_requests

# 1. Initialize Page Config, Theme State, and Ensure Background API
ensure_api_running()
init_page_and_theme()

# 2. Gate: Sub-App Session Selector (If not yet authenticated)
if not st.session_state.get("authenticated"):
    render_session_selector()
    st.stop()

# 3. Sidebar (Active Profile, Sidebar Navigation Tabs, Switch Persona, Health Indicator)
token, persona, is_manager, is_admin, selected_tab = render_sidebar()

# 4. Main Layout Header: Brand & Identity with Dynamic Active Tab Title
col_hdr_logo, col_hdr_content = st.columns([0.8, 6.2])
with col_hdr_logo:
    if os.path.exists(GUNUNGAN_LOGO):
        st.image(GUNUNGAN_LOGO, width=180)
with col_hdr_content:
    st.markdown(f"<h2 style='margin-bottom:2px; color: var(--text-primary); font-weight:800;'>{selected_tab}</h2>", unsafe_allow_html=True)
    st.markdown(
        "<div style='color: var(--accent-sky); font-weight:600; font-size:1.02rem; margin-bottom:2px;'>"
        "PT Nusantara Digital · Portal Layanan Mandiri HR (Miyo)"
        "</div>",
        unsafe_allow_html=True,
    )
    st.caption("Sistem terintegrasi kebijakan perusahaan, permohonan cuti, kalender operasional, dan analitik SDM.")
st.markdown("---")

# 5. Dynamic Module Rendering based on Sidebar Tab Selection
if selected_tab == "Asisten Kebijakan":
    render_tab_chat(token, persona, is_manager, is_admin)
elif selected_tab == "Permohonan Cuti Saya":
    render_tab_my_requests(token, persona, is_admin)
elif selected_tab == "Kalender Cuti":
    render_tab_calendar(token, persona, is_manager, is_admin)
elif selected_tab == "Persetujuan Tim" and is_manager:
    render_tab_team_approvals(token, persona, is_admin)
elif selected_tab == "Monitoring Operasional" and is_admin:
    render_tab_monitoring(token)
else:
    render_tab_chat(token, persona, is_manager, is_admin)
