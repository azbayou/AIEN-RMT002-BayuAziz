"""Sub-App Session Selector with Minimalist SSO List Row (Linear / Google Workspace Style)."""
from __future__ import annotations

import json
import os

import httpx
import streamlit as st

from ui.config import API_URL, BASE_DIR, GUNUNGAN_LOGO, MIYO_LOGO
from ui.icons import svg_icon
from ui_contract import select_persona


def _load_system_employees() -> list[dict]:
    """Read employee directory dynamically from data/employees.json."""
    emp_path = BASE_DIR / "data" / "employees.json"
    if emp_path.exists():
        try:
            return json.loads(emp_path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return []


def render_session_selector() -> None:
    """Render minimalist SSO list rows with zero-emoticon styling and step-up auth."""
    cur_theme = st.session_state.get("ui_theme", "dark")

    # Top Bar: Theme Toggle in top-right with Material Icon (Matahari / Bulan)
    col_top_space, col_top_theme = st.columns([6.2, 0.6])
    with col_top_theme:
        theme_icon = ":material/light_mode:" if cur_theme == "dark" else ":material/dark_mode:"
        theme_help = "Beralih ke Mode Terang" if cur_theme == "dark" else "Beralih ke Mode Gelap"
        if st.button("", icon=theme_icon, key="btn_theme_toggle_login", help=theme_help, use_container_width=True):
            st.session_state["ui_theme"] = "light" if cur_theme == "dark" else "dark"
            st.rerun()

    # Centered Brand Logo (Logo Miyo di Bagian Atas Tengah)
    if os.path.exists(MIYO_LOGO):
        col_l, col_logo, col_r = st.columns([2.6, 0.8, 2.6])
        with col_logo:
            st.image(MIYO_LOGO, use_container_width=True)

    # Hero Intro Header (Quiet Precision & Human Warmth)
    st.markdown(
        """
        <div style="text-align: center; margin-bottom: 2rem;">
            <div style="display: inline-flex; align-items: center; gap: 6px; padding: 4px 12px; border-radius: 9999px; background-color: var(--accent-orange-subtle); border: 1px solid var(--border-subtle); margin-bottom: 12px;">
                <span style="display: inline-block; width: 6px; height: 6px; border-radius: 50%; background-color: var(--accent-orange);"></span>
                <span style="font-size: 0.75rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.08em; color: var(--accent-orange);">
                    PORTAL LAYANAN MANDIRI HR
                </span>
            </div>
            <h1 style="font-size: 2rem; font-weight: 700; margin: 0 0 6px 0; color: var(--text-primary); letter-spacing: -0.03em;">
                PT NUSANTARA DIGITAL
            </h1>
            <div style="font-size: 1.05rem; font-weight: 500; color: var(--accent-orange); margin-bottom: 8px;">
                Asisten Kebijakan HR dan Pengajuan Cuti (Miyo)
            </div>
            <p style="color: var(--text-secondary); font-size: 0.88rem; max-width: 600px; margin: 0 auto; line-height: 1.5;">
                Pilih profil aktif Anda untuk masuk ke sistem layanan mandiri.
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    employees = _load_system_employees()
    if not employees:
        st.error("[ERROR] Direktori pegawai tidak ditemukan di data/employees.json.")
        return

    # Check if a step-up authentication modal/panel is pending
    pending_user = st.session_state.get("pending_stepup_user")
    if pending_user:
        st.markdown(
            f"""
            <div style="background-color: var(--bg-surface-elevated); border: 1px solid var(--accent-orange); border-radius: 12px; padding: 20px; max-width: 620px; margin: 0 auto 24px auto; box-shadow: 0 8px 24px rgba(0, 0, 0, 0.2);">
                <div style="display: flex; align-items: center; gap: 8px; font-size: 0.78rem; text-transform: uppercase; letter-spacing: 0.08em; color: var(--accent-orange); font-weight: 700; margin-bottom: 6px;">
                    Verifikasi Keamanan Akses (Step-Up Authentication)
                </div>
                <div style="font-size: 1.15rem; font-weight: 700; color: var(--text-primary); margin-bottom: 4px;">
                    {pending_user['display_name']}
                </div>
                <div style="font-size: 0.85rem; color: var(--text-secondary); margin-bottom: 12px;">
                    ID: <code style="font-family: var(--font-mono); color: var(--accent-orange);">{pending_user['employee_id']}</code> · Role: <b>{pending_user['role'].upper()}</b> ({pending_user.get('department', '-')})
                </div>
                <div style="font-size: 0.83rem; color: var(--text-muted); margin-bottom: 14px;">
                    Akun ini memiliki hak akses manajerial/monitoring. Masukkan password terdaftar untuk mengaktifkan sesi.
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        with st.form("stepup_password_form"):
            entered_password = st.text_input(
                "Password Akun:",
                type="password",
                placeholder="Masukkan password akun",
                help="Masukkan password untuk otentikasi akun.",
            )
            col_sub, col_cancel = st.columns([1.2, 1])
            with col_sub:
                submit_stepup = st.form_submit_button("Konfirmasi & Masuk", type="primary", use_container_width=True)
            with col_cancel:
                cancel_stepup = st.form_submit_button("Batal", use_container_width=True)

            if submit_stepup:
                clean_pwd = entered_password.strip()
                if not clean_pwd:
                    st.error("Password tidak boleh kosong.")
                else:
                    try:
                        resp = httpx.post(
                            f"{API_URL}/api/v1/auth/login",
                            json={"username": pending_user["username"], "password": clean_pwd},
                            timeout=10.0,
                        )
                        if resp.status_code == 200:
                            data = resp.json()
                            profile = data["profile"]
                            access_token = data["access_token"]
                            active_persona = {
                                "employee_id": profile["employee_id"],
                                "label": f"{profile['display_name']} — {profile.get('department') or profile['role'].title()}",
                                "scenario": f"Akun {profile['role']} terverifikasi.",
                                "demo_token": access_token,
                            }
                            st.session_state["authenticated"] = True
                            st.session_state["active_persona"] = active_persona
                            select_persona(st.session_state, active_persona)
                            st.session_state["chat_history"] = []
                            st.session_state["confirmed_proposals"] = set()
                            st.session_state.pop("pending_stepup_user", None)
                            st.rerun()
                        elif resp.status_code == 401:
                            st.error("[AUTENTIKASI GAGAL] Password salah. Silakan coba kembali.")
                        else:
                            st.error(f"[ERROR {resp.status_code}] {resp.text}")
                    except Exception as err:
                        st.error(f"[KONEKSI GAGAL] Gagal menghubungi backend API: {err}")

            if cancel_stepup:
                st.session_state.pop("pending_stepup_user", None)
                st.rerun()

        st.markdown("---")

    # Render Minimalist SSO List Rows (Linear Style)
    st.markdown('<div class="sso-list-wrapper">', unsafe_allow_html=True)

    for idx, emp in enumerate(employees):
        emp_id = emp["employee_id"]
        role = emp.get("role", "employee")
        is_privileged = role in ("manager", "monitoring_admin")

        # Initial letter for avatar
        initials = "".join([part[0] for part in emp["display_name"].split()[:2]]).upper()

        # Role badge metadata
        if role == "manager":
            role_label = "MANAGER"
            role_badge_style = "background: rgba(218, 119, 86, 0.15); color: var(--accent-orange); border: 1px solid var(--accent-orange);"
        elif role == "monitoring_admin":
            role_label = "ADMIN"
            role_badge_style = "background: rgba(168, 85, 247, 0.15); color: var(--accent-violet); border: 1px solid var(--accent-violet);"
        else:
            role_label = "PEGAWAI"
            role_badge_style = "background: var(--bg-surface); color: var(--text-secondary); border: 1px solid var(--border-subtle);"

        balances = emp.get("balances", {})
        annual_bal = balances.get("annual")
        quota_text = f"Saldo Cuti: {annual_bal} Hari" if annual_bal is not None else "Hak Akses: Penuh"
        auth_note = "Verifikasi Sandi Wajib" if is_privileged else "Akses Langsung (SSO)"

        # Render row item with columns
        with st.container():
            col_avatar, col_meta, col_btn = st.columns([0.65, 3.8, 1.45])

            with col_avatar:
                st.markdown(
                    f'<div class="sso-avatar">{initials}</div>',
                    unsafe_allow_html=True,
                )

            with col_meta:
                st.markdown(
                    f"""
                    <div style="padding-top: 2px;">
                        <div class="sso-name-title">
                            <span>{emp['display_name']}</span>
                            <span class="sso-badge-role" style="{role_badge_style}">{role_label}</span>
                            <span style="font-family: var(--font-mono); font-size: 0.78rem; color: var(--text-muted); background: var(--bg-surface); padding: 1px 6px; border-radius: 4px; border: 1px solid var(--border-subtle);">
                                {emp_id}
                            </span>
                        </div>
                        <div class="sso-meta-sub">
                            <span>{emp.get('department', 'Engineering')}</span>
                            <span>•</span>
                            <span style="color: var(--accent-orange); font-weight: 500;">{quota_text}</span>
                            <span>•</span>
                            <span style="color: var(--text-muted); font-size: 0.78rem;">{auth_note}</span>
                        </div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

            with col_btn:
                btn_label = f"Verifikasi" if is_privileged else "Masuk (SSO)"
                btn_type = "secondary" if is_privileged else "primary"

                if st.button(btn_label, key=f"btn_sso_row_{emp_id}", use_container_width=True, type=btn_type):
                    if is_privileged:
                        st.session_state["pending_stepup_user"] = emp
                        st.rerun()
                    else:
                        active_persona = {
                            "employee_id": emp_id,
                            "label": f"{emp['display_name']} — {emp.get('department', 'Engineering')}",
                            "scenario": "Akun pegawai reguler terotentikasi.",
                            "demo_token": emp["token"],
                        }
                        st.session_state["authenticated"] = True
                        st.session_state["active_persona"] = active_persona
                        select_persona(st.session_state, active_persona)
                        st.session_state["chat_history"] = []
                        st.session_state["confirmed_proposals"] = set()
                        st.rerun()

            st.markdown(
                '<div style="height: 1px; background-color: var(--border-subtle); margin: 6px 0 14px 0;"></div>',
                unsafe_allow_html=True,
            )

    st.markdown("</div>", unsafe_allow_html=True)

    # Expandable Info on Test Credentials
    with st.expander("Informasi Kredensial Pengujian (Demo)", expanded=False):
        st.markdown(
            """
            | ID Pegawai | Nama Pegawai | Role | Departemen | Token Bearer | Password Verifikasi |
            | :--- | :--- | :--- | :--- | :--- | :--- |
            | `EMP-001` | Alya Pratama | `employee` | Engineering | `token-alya` | *(Akses Langsung SSO)* |
            | `EMP-002` | Bima Santoso | `employee` | Engineering | `token-bima` | *(Akses Langsung SSO)* |
            | `MGR-001` | Raka Wijaya | `manager` | Engineering | `token-manager` | `Password#123` |
            | `ADM-001` | Monitoring Admin | `monitoring_admin` | HR & People Ops | `token-admin` | `Password#123` |
            """
        )
