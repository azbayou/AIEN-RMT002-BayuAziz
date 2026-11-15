from __future__ import annotations

import os
import uuid
from pathlib import Path

import httpx
import streamlit as st

from ui_contract import API_PATHS, load_personas, select_persona


API_URL = os.getenv("API_URL", "http://localhost:8000").rstrip("/")


def fetch_personas(api_url: str, fallback_path: Path) -> list[dict]:
    """Fetch demo personas from backend API, falling back to local demo_personas.json if unreachable."""
    try:
        resp = httpx.get(f"{api_url}{API_PATHS['personas']}", timeout=5.0)
        if resp.status_code == 200:
            rows = resp.json()
            if isinstance(rows, list) and rows:
                formatted: list[dict] = []
                for row in rows:
                    if not isinstance(row, dict) or not row.get("employee_id"):
                        continue
                    emp_id = row["employee_id"]
                    display_name = row.get("display_name") or emp_id
                    dept = row.get("department") or ""
                    role = row.get("role") or "employee"
                    demo_token = row.get("demo_token") or ""
                    formatted.append(
                        {
                            "employee_id": emp_id,
                            "username": row.get("username") or emp_id,
                            "label": f"{display_name} — {dept or role}",
                            "scenario": f"Akun {role} ({dept or '-'})",
                            "demo_token": demo_token,
                            "requires_password": bool(row.get("requires_password") or not demo_token),
                        }
                    )
                if formatted:
                    return formatted
    except Exception:
        pass
    return load_personas(fallback_path)


def request(method: str, path: str, token: str, **kwargs):
    headers = {"Authorization": f"Bearer {token}"}
    response = httpx.request(method, f"{API_URL}{path}", headers=headers, timeout=40, **kwargs)
    if response.is_error:
        detail = response.json().get("detail", response.text)
        st.error(f"API {response.status_code}: {detail}")
        return None
    return response.json()


st.set_page_config(page_title="Asisten HR Nusantara Digital", page_icon="🧭", layout="wide")
st.title("Asisten Kebijakan HR dan Cuti")
st.caption("Data dan token pada aplikasi ini sepenuhnya sintetis untuk kebutuhan pembelajaran.")

personas = fetch_personas(API_URL, Path(__file__).with_name("demo_personas.json"))
persona = st.sidebar.selectbox("Persona demo", personas, format_func=lambda item: item["label"])
select_persona(st.session_state, persona)
st.sidebar.caption(persona["scenario"])
token_key = f"auth_token_{persona['employee_id']}"
token = st.session_state.get(token_key) or persona.get("demo_token", "")
if persona.get("requires_password") and not token:
    with st.sidebar.form(f"login_form_{persona['employee_id']}"):
        pwd = st.text_input("Password akun istimewa", type="password")
        if st.form_submit_button("Masuk"):
            try:
                login_resp = httpx.post(
                    f"{API_URL}/api/v1/auth/login",
                    json={"username": persona.get("username") or persona["employee_id"], "password": pwd},
                    timeout=10.0,
                )
                if login_resp.status_code == 200:
                    login_data = login_resp.json()
                    st.session_state[token_key] = login_data["access_token"]
                    st.rerun()
                else:
                    st.error("Password salah atau akun tidak valid.")
            except Exception as exc:
                st.error(f"Gagal menghubungi API login: {exc}")
    st.sidebar.info("Masukkan password untuk mengaktifkan akses akun manajer/admin.")

chat_tab, leave_tab, monitor_tab = st.tabs(["Percakapan", "Permintaan Cuti", "Monitoring"])

with chat_tab:
    message = st.text_area("Pertanyaan atau permintaan", placeholder="Berapa saldo cuti saya?")
    if st.button("Kirim", type="primary", disabled=not message.strip()):
        result = request("POST", API_PATHS["chat"], token, json={"message": message})
        if result:
            st.session_state["last_chat"] = result
    result = st.session_state.get("last_chat")
    if result:
        st.markdown(result["answer"])
        st.caption(f"Outcome: {result['outcome']} · Trace: {result['trace_id']}")
        if result["citations"]:
            with st.expander("Sumber kebijakan"):
                for citation in result["citations"]:
                    st.markdown(f"**{citation['document_id']} — {citation['section']}**")
                    st.write(citation["excerpt"])
        proposal = result.get("action_proposal")
        if proposal:
            st.warning("Tindakan belum dijalankan. Periksa detail lalu konfirmasikan.")
            st.json(proposal)
            key_name = f"idem_{proposal['proposal_id']}"
            st.session_state.setdefault(key_name, str(uuid.uuid4()))
            if st.button("Konfirmasi pembuatan permintaan pending", key=proposal["proposal_id"]):
                confirmed = request(
                    "POST",
                    API_PATHS["confirm"].format(proposal_id=proposal["proposal_id"]),
                    token,
                    json={"idempotency_key": st.session_state[key_name]},
                )
                if confirmed:
                    st.success(f"Permintaan {confirmed['request_id']} berstatus {confirmed['status']}.")

with leave_tab:
    if st.button("Muat permintaan saya"):
        data = request("GET", API_PATHS["my_requests"], token)
        if data is not None:
            st.dataframe(data, use_container_width=True)

with monitor_tab:
    st.info("Gunakan token monitoring admin untuk membuka metrik dan alert agregat.")
    if st.button("Muat monitoring"):
        summary = request("GET", API_PATHS["monitoring_summary"], token)
        alerts = request("GET", API_PATHS["monitoring_alerts"], token)
        if summary:
            columns = st.columns(4)
            columns[0].metric("Runs", summary["run_count"])
            columns[1].metric("Error rate", f"{float(summary['error_rate']):.1%}")
            columns[2].metric("p95 latency", f"{int(summary['p95_latency_ms'])} ms")
            columns[3].metric("Tool calls", summary["tool_calls"])
        if alerts is not None:
            st.subheader("Alert aktif")
            st.json(alerts)

