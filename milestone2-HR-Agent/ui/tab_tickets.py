"""HR Support & Escalation Tickets tab with filtering and status management."""
from __future__ import annotations

import html
import time

import streamlit as st

from ui.api_client import api_request
from ui_contract import API_PATHS

_TICKET_STATUS_OPTIONS = ("pending", "on progress", "done")
_STATUS_BADGE_CLASS = {
    "pending": "status-badge-pending",
    "on progress": "status-badge-pending",
    "done": "status-badge-approved",
}
_STATUS_LABEL = {
    "pending": "Pending",
    "on progress": "On Progress",
    "done": "Done",
}


def render_tab_tickets(token: str, persona: dict, is_manager: bool, is_admin: bool) -> None:
    """Render Tickets tab: list HR tickets, filter/search, and update status for Manager/Admin."""
    st.subheader("Daftar Tiket Dukungan & Eskalasi HR")
    if is_manager or is_admin:
        st.caption("Pantau seluruh tiket eskalasi pegawai dan perbarui progres penanganannya.")
    else:
        st.caption(f"Daftar tiket dukungan dan eskalasi HR milik {persona.get('label', 'Anda')}.")

    col_refresh, col_status, col_search = st.columns([1.0, 1.4, 2.6])
    with col_refresh:
        if st.button("Segarkan Tiket", key="btn_refresh_tickets", use_container_width=True):
            st.rerun()
    with col_status:
        status_filter = st.selectbox(
            "Filter Status",
            options=["all", "pending", "on progress", "done"],
            format_func=lambda s: "Semua Status" if s == "all" else _STATUS_LABEL.get(s, s),
            key="tickets_status_filter",
            label_visibility="collapsed",
        )
    with col_search:
        search_query = st.text_input(
            "Cari Tiket",
            placeholder="Cari ID tiket, kategori, pegawai, atau ringkasan...",
            key="tickets_search_query",
            label_visibility="collapsed",
        )

    tickets = api_request("GET", API_PATHS["tickets"], token)
    if tickets is None:
        return

    if not tickets:
        st.info("Belum ada tiket dukungan atau eskalasi HR yang tercatat.")
        return

    total_count = len(tickets)
    pending_count = sum(1 for t in tickets if (t.get("status") or "pending") == "pending")
    progress_count = sum(1 for t in tickets if t.get("status") == "on progress")
    done_count = sum(1 for t in tickets if t.get("status") == "done")

    m_c1, m_c2, m_c3, m_c4 = st.columns(4)
    m_c1.metric("Total Tiket", total_count)
    m_c2.metric("Pending", pending_count)
    m_c3.metric("On Progress", progress_count)
    m_c4.metric("Done", done_count)
    st.markdown("---")

    q_lower = search_query.strip().lower()
    filtered = []
    for ticket in tickets:
        t_status = ticket.get("status") or "pending"
        if status_filter != "all" and t_status != status_filter:
            continue
        if q_lower:
            haystack = " ".join(
                str(ticket.get(field) or "")
                for field in ("ticket_id", "employee_id", "employee_name", "department", "category", "summary")
            ).lower()
            if q_lower not in haystack:
                continue
        filtered.append(ticket)

    if not filtered:
        st.info("Tidak ada tiket yang cocok dengan filter atau kata kunci pencarian.")
        return

    can_manage = is_manager or is_admin
    for ticket in filtered:
        ticket_id = str(ticket.get("ticket_id") or "-")
        emp_id = str(ticket.get("employee_id") or "-")
        emp_name = str(ticket.get("employee_name") or emp_id)
        dept = str(ticket.get("department") or "General")
        category = str(ticket.get("category") or "general")
        summary = str(ticket.get("summary") or "-")
        t_status = str(ticket.get("status") or "pending")
        created_at = str(ticket.get("created_at") or "")[:19].replace("T", " ")
        updated_at = str(ticket.get("updated_at") or "")[:19].replace("T", " ")
        updated_by = str(ticket.get("updated_by") or "")

        badge_cls = _STATUS_BADGE_CLASS.get(t_status, "status-badge-pending")
        badge_txt = _STATUS_LABEL.get(t_status, t_status.upper())

        updated_meta = (
            f" · Diperbarui: {html.escape(updated_at)} oleh <code>{html.escape(updated_by)}</code>"
            if updated_at and updated_by
            else ""
        )

        with st.container():
            st.markdown(
                f"""
                <div style="background-color: var(--bg-surface-elevated); border: 1px solid var(--border-subtle); border-radius: 10px; padding: 14px 18px; margin-bottom: 10px;">
                    <div style="display: flex; justify-content: space-between; align-items: center; gap: 12px; margin-bottom: 8px;">
                        <div style="font-weight: 700; font-size: 1.02rem; color: var(--text-primary);">
                            <code>{html.escape(ticket_id)}</code> — {html.escape(category)}
                        </div>
                        <div><span class="{badge_cls}">{html.escape(badge_txt)}</span></div>
                    </div>
                    <div style="color: var(--text-secondary); font-size: 0.92rem; margin-bottom: 6px;">
                        <b>Pemohon:</b> {html.escape(emp_name)} (<code>{html.escape(emp_id)}</code> · {html.escape(dept)})
                    </div>
                    <div style="color: var(--text-primary); font-size: 0.92rem; line-height: 1.45; margin-bottom: 8px;">
                        {html.escape(summary)}
                    </div>
                    <div style="color: var(--text-muted); font-size: 0.78rem;">
                        Dibuat pada: {html.escape(created_at)} UTC{updated_meta}
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )

            if can_manage:
                current_idx = (
                    _TICKET_STATUS_OPTIONS.index(t_status)
                    if t_status in _TICKET_STATUS_OPTIONS
                    else 0
                )
                u_col1, u_col2, _ = st.columns([1.8, 1.2, 3.0])
                with u_col1:
                    new_status = st.selectbox(
                        "Status Tiket",
                        options=list(_TICKET_STATUS_OPTIONS),
                        index=current_idx,
                        format_func=lambda s: _STATUS_LABEL.get(s, s),
                        key=f"sel_ticket_status_{ticket_id}",
                        label_visibility="collapsed",
                    )
                with u_col2:
                    if st.button(
                        "Perbarui Status",
                        key=f"btn_update_ticket_{ticket_id}",
                        type="primary",
                        use_container_width=True,
                        disabled=(new_status == t_status),
                    ):
                        res = api_request(
                            "PATCH",
                            API_PATHS["ticket_status"].format(ticket_id=ticket_id),
                            token,
                            json={"status": new_status},
                        )
                        if res:
                            st.success(f"Status tiket {ticket_id} diperbarui menjadi '{new_status}'.")
                            time.sleep(0.4)
                            st.rerun()

            st.markdown(
                "<hr style='border: 0.5px solid var(--border-subtle); margin: 8px 0 12px 0;' />",
                unsafe_allow_html=True,
            )
