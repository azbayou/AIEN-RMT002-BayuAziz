"""Sub-App Session Selector with Step-Up Password Authentication for Privileged Roles."""
from __future__ import annotations

import json
import os
import time

import httpx
import streamlit as st

from ui.config import API_URL, BASE_DIR, GUNUNGAN_LOGO
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
    """Render enterprise sub-app user directory with zero-emoticon styling and step-up auth."""
    # Top Bar: Theme Toggle in top-right
    col_top_space, col_top_theme = st.columns([5.5, 1.2])
    with col_top_theme:
        cur_theme = st.session_state.get("ui_theme", "dark")
        new_theme_label = "Mode Terang" if cur_theme == "dark" else "Mode Gelap"
        if st.button(new_theme_label, key="btn_theme_toggle_login", use_container_width=True):
            st.session_state["ui_theme"] = "light" if cur_theme == "dark" else "dark"
            st.rerun()

    # Centered Brand Logo
    if os.path.exists(GUNUNGAN_LOGO):
        col_l, col_logo, col_r = st.columns([2.3, 1, 2.3])
        with col_logo:
            st.image(GUNUNGAN_LOGO, use_container_width=True)

    # Hero Intro
    st.markdown(
        """
        <div class="login-hero">
            <span class="login-badge">Portal Layanan Mandiri HR</span>
            <h1 style="font-size: 2rem; font-weight: 800; margin-top: 4px; margin-bottom: 4px; color: var(--accent-sky);">
                PT NUSANTARA DIGITAL
            </h1>
            <div style="font-weight: 600; font-size: 1.1rem; color: var(--text-primary); margin-bottom: 6px;">
                Asisten Kebijakan HR dan Pengajuan Cuti (Miyo)
            </div>
            <p style="color: var(--text-muted); font-size: 0.9rem; max-width: 650px; margin: 0 auto 1.5rem auto;">
                Sub-aplikasi internal terintegrasi. Pilih profil aktif Anda untuk memulai sesi layanan mandiri.
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
            <div style="background-color: var(--bg-surface-elevated); border: 1px solid var(--accent-sky); border-radius: 12px; padding: 20px; max-width: 540px; margin: 0 auto 24px auto;">
                <div style="font-size: 0.78rem; text-transform: uppercase; letter-spacing: 0.08em; color: var(--accent-sky); font-weight: 700; margin-bottom: 4px;">
                    Verifikasi Keamanan Akses (Step-Up Authentication)
                </div>
                <div style="font-size: 1.15rem; font-weight: 700; color: var(--text-primary); margin-bottom: 4px;">
                    {pending_user['display_name']}
                </div>
                <div style="font-size: 0.85rem; color: var(--text-muted); margin-bottom: 14px;">
                    ID: <code>{pending_user['employee_id']}</code> · Role: <b>{pending_user['role'].upper()}</b> ({pending_user.get('department', '-')})
                </div>
                <div style="font-size: 0.83rem; color: var(--text-secondary); margin-bottom: 12px;">
                    Akun ini memiliki kewenangan manajerial/administratif. Masukkan password untuk mengaktifkan sesi.
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        with st.form("stepup_password_form"):
            entered_password = st.text_input(
                "Password Akun:",
                type="password",
                placeholder="Masukkan password",
                help="Masukkan password terdaftar untuk akun ini.",
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

    # Render User Directory Grid (4 Columns)
    cols = st.columns(len(employees))
    for idx, emp in enumerate(employees):
        emp_id = emp["employee_id"]
        role = emp.get("role", "employee")
        is_privileged = role in ("manager", "monitoring_admin")

        badge_txt = "MANAGER" if role == "manager" else ("ADMIN" if role == "monitoring_admin" else "PEGAWAI")
        badge_style = "border-color: #38bdf8; color: #38bdf8;" if is_privileged else "border-color: #334155; color: #94a3b8;"

        balances = emp.get("balances", {})
        annual_bal = balances.get("annual")
        quota_text = f"Saldo Cuti Tahunan: {annual_bal} Hari" if annual_bal is not None else "Akses: Audit & Monitoring"
        auth_req_text = "Verifikasi Password Wajib" if is_privileged else "Akses Langsung (SSO)"

        with cols[idx]:
            st.markdown(
                f"""
                <div class="persona-login-card">
                    <div>
                        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
                            <span style="font-family: monospace; font-size: 0.8rem; background: var(--bg-surface); padding: 2px 8px; border-radius: 4px; border: 1px solid var(--border-subtle); color: var(--accent-sky);">
                                {emp_id}
                            </span>
                            <span style="font-size: 0.72rem; font-weight: 700; padding: 1px 6px; border-radius: 4px; border: 1px solid; {badge_style}">
                                {badge_txt}
                            </span>
                        </div>
                        <div class="persona-login-name">{emp['display_name']}</div>
                        <div class="persona-login-role">{emp.get('department', '-')}</div>
                        <div style="background-color: var(--bg-surface); border: 1px solid var(--border-subtle); color: var(--text-secondary); padding: 4px 8px; border-radius: 6px; font-size: 0.78rem; font-weight: 600; margin-bottom: 8px;">
                            {quota_text}
                        </div>
                        <div style="font-size: 0.75rem; color: var(--text-muted); margin-bottom: 14px;">
                            Otorisasi: {auth_req_text}
                        </div>
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )

            btn_label = f"Verifikasi {emp['display_name'].split()[0]}" if is_privileged else f"Masuk ({emp['display_name'].split()[0]})"
            btn_type = "secondary" if is_privileged else "primary"

            if st.button(btn_label, key=f"btn_sel_user_{emp_id}", use_container_width=True, type=btn_type):
                if is_privileged:
                    st.session_state["pending_stepup_user"] = emp
                    st.rerun()
                else:
                    # Role employee: direct enter binding their unique bearer token
                    active_persona = {
                        "employee_id": emp_id,
                        "label": f"{emp['display_name']} — {emp.get('department', 'Engineering')}",
                        "scenario": f"Akun pegawai reguler terotentikasi.",
                        "demo_token": emp["token"],
                    }
                    st.session_state["authenticated"] = True
                    st.session_state["active_persona"] = active_persona
                    select_persona(st.session_state, active_persona)
                    st.session_state["chat_history"] = []
                    st.session_state["confirmed_proposals"] = set()
                    st.rerun()

    st.markdown("---")

    # Expandable Info on Test Credentials
    with st.expander("Informasi Kredensial Pengujian (Demo)", expanded=False):
        st.markdown(
            """
            | ID Pegawai | Nama Pegawai | Role | Departemen | Token Bearer | Password Verifikasi |
            | :--- | :--- | :--- | :--- | :--- | :--- |
            | `EMP-001` | Alya Pratama | `employee` | Engineering | `token-alya` | *(Akses Langsung)* |
            | `EMP-002` | Bima Santoso | `employee` | Engineering | `token-bima` | *(Akses Langsung)* |
            | `MGR-001` | Raka Wijaya | `manager` | Engineering | `token-manager` | `Password#123` |
            | `ADM-001` | Monitoring Admin | `monitoring_admin` | HR & People Ops | `token-admin` | `Password#123` |
            """
        )
