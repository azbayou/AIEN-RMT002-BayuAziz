"""Team Leave Approvals tab for Manager and Admin roles."""
from __future__ import annotations

import base64
import time

import streamlit as st

from ui.api_client import api_request


def render_tab_team_approvals(token: str, persona: dict, is_admin: bool) -> None:
    """Render Tab 4: Team Leave Approvals & HR Analytics."""
    st.subheader("Persetujuan Cuti Anggota Tim")
    st.caption("Review permohonan cuti dari bawahan langsung (Manager) atau seluruh divisi (Admin).")

    col_sync_team, _ = st.columns([1, 4])
    with col_sync_team:
        if st.button("Segarkan Data Tim", key="btn_refresh_team_leaves", use_container_width=True):
            st.rerun()

    team_leaves = api_request("GET", "/api/v1/manager/leave-requests", token)

    # Ringkasan Visual Analitik SDM Tim
    analytics_data = api_request("GET", "/api/v1/analytics/overview", token)
    if analytics_data:
        st.markdown("#### Ringkasan Analitik dan Tren SDM")
        team_sz = analytics_data.get("team_size", 0)
        days_by_tp = analytics_data.get("days_by_leave_type", {})
        low_bals = analytics_data.get("low_balance_employees", [])

        an_c1, an_c2, an_c3 = st.columns(3)
        an_c1.metric("Anggota Tim", f"{team_sz} Pegawai")
        an_c2.metric("Total Hari Cuti Aktif", f"{sum(days_by_tp.values())} Hari")
        an_c3.metric("Risiko Saldo Rendah", f"{len(low_bals)} Pegawai")

        if low_bals:
            with st.expander(f"Pegawai dengan Sisa Saldo Cuti Rendah (<= 3 hari) — {len(low_bals)} orang", expanded=True):
                for lb in low_bals:
                    st.warning(
                        f"**{lb.get('display_name')}** (`{lb.get('employee_id')}`): Sisa cuti tahunan tinggal **{lb.get('annual_remaining')} hari**"
                    )
        st.markdown("---")

    if team_leaves is not None:
        if not team_leaves:
            st.info("Tidak ada permohonan cuti anggota tim yang tercatat.")
        else:
            pending_reqs = [r for r in team_leaves if r.get("status") == "pending_manager_review"]
            approved_count = sum(1 for r in team_leaves if r.get("status") == "approved")
            rejected_count = sum(1 for r in team_leaves if r.get("status") == "rejected")

            m_c1, m_c2, m_c3 = st.columns(3)
            m_c1.metric("Menunggu Persetujuan", len(pending_reqs))
            m_c2.metric("Disetujui", approved_count)
            m_c3.metric("Ditolak", rejected_count)

            st.markdown("---")

            if not pending_reqs:
                st.success("Seluruh permohonan cuti anggota tim telah selesai diproses.")
            else:
                st.markdown("#### Permohonan Menunggu Keputusan")
                for req in pending_reqs:
                    req_id = req.get("request_id")
                    emp_name = req.get("employee_name") or req.get("employee_id")
                    emp_id = req.get("employee_id", "-")
                    leave_type = str(req.get("leave_type", "")).capitalize()
                    b_days = req.get("business_days", 0)
                    s_date = req.get("start_date")
                    e_date = req.get("end_date")

                    with st.container():
                        st.markdown(
                            f"""
                            <div style="background-color: var(--bg-surface-elevated); border: 1px solid var(--border-subtle); border-radius: 10px; padding: 14px 18px; margin-bottom: 8px;">
                                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
                                    <div style="font-weight: 700; font-size: 1.05rem; color: var(--text-primary);">
                                        <b>{emp_name}</b> (<code>{emp_id}</code>) — ID: <code>{req_id}</code>
                                    </div>
                                    <div><span class="status-badge-pending">Menunggu Review</span></div>
                                </div>
                                <div style="color: var(--text-secondary); font-size: 0.92rem;">
                                    <b>Jenis Cuti:</b> Cuti {leave_type} | <b>Periode:</b> {s_date} s/d {e_date} (<b>{b_days} hari kerja</b>)
                                </div>
                                <div style="color: var(--text-muted); font-size: 0.8rem; margin-top: 4px;">
                                    Diajukan pada: {req.get('created_at', '')[:19].replace('T', ' ')} UTC
                                </div>
                            </div>
                            """,
                            unsafe_allow_html=True,
                        )

                        if req.get("leave_type") == "sick":
                            if req.get("has_attachment"):
                                att_fn = req.get("attachment_filename") or "surat_dokter"
                                st.markdown(f"**Lampiran Surat Dokter:** `{att_fn}`")
                                with st.expander(f"Tinjau Lampiran Surat Dokter: {att_fn}", expanded=True):
                                    att_data = api_request("GET", f"/api/v1/leave-requests/{req_id}/attachment", token)
                                    if att_data:
                                        b64_val = att_data.get("content_base64", "")
                                        raw_bytes = base64.b64decode(b64_val)
                                        c_type = att_data.get("content_type", "")
                                        f_name = att_data.get("filename", att_fn)
                                        if c_type in ("image/png", "image/jpeg"):
                                            st.image(raw_bytes, caption=f_name, use_container_width=True)
                                            st.download_button(
                                                "Unduh Gambar Surat Dokter",
                                                data=raw_bytes,
                                                file_name=f_name,
                                                mime=c_type,
                                                key=f"dl_mgr_img_{req_id}",
                                            )
                                        elif c_type == "application/pdf":
                                            st.markdown(
                                                f'<iframe src="data:application/pdf;base64,{b64_val}" width="100%" height="450px" style="border: 1px solid var(--border-subtle); border-radius: 8px;"></iframe>',
                                                unsafe_allow_html=True,
                                            )
                                            st.download_button(
                                                "Unduh PDF Surat Dokter",
                                                data=raw_bytes,
                                                file_name=f_name,
                                                mime="application/pdf",
                                                key=f"dl_mgr_pdf_{req_id}",
                                            )
                            else:
                                st.warning("Pegawai belum melampirkan surat dokter")

                        note_key = f"note_{req_id}"
                        review_note = st.text_input(
                            "Catatan Review Manajer",
                            value="Reviewed by manager",
                            key=note_key,
                            max_chars=300,
                        )
                        b_col1, b_col2, _ = st.columns([1.5, 1.5, 3])
                        with b_col1:
                            if st.button("Setujui Permohonan", key=f"btn_appr_{req_id}", type="primary", use_container_width=True):
                                res = api_request(
                                    "POST",
                                    f"/api/v1/manager/leave-requests/{req_id}/review",
                                    token,
                                    json={"decision": "approved", "review_note": review_note.strip() or "Approved by manager"},
                                )
                                if res:
                                    st.success(f"Permohonan cuti {req_id} disetujui. Audit Ref: {res.get('audit_reference')}")
                                    time.sleep(0.5)
                                    st.rerun()
                        with b_col2:
                            if st.button("Tolak Permohonan", key=f"btn_rej_{req_id}", use_container_width=True):
                                res = api_request(
                                    "POST",
                                    f"/api/v1/manager/leave-requests/{req_id}/review",
                                    token,
                                    json={"decision": "rejected", "review_note": review_note.strip() or "Rejected by manager"},
                                )
                                if res:
                                    st.warning(f"Permohonan cuti {req_id} ditolak. Audit Ref: {res.get('audit_reference')}")
                                    time.sleep(0.5)
                                    st.rerun()
                        st.markdown("<hr style='border: 0.5px solid var(--border-subtle); margin: 12px 0;' />", unsafe_allow_html=True)

            # Riwayat Review Tim
            history_reqs = [r for r in team_leaves if r.get("status") in ("approved", "rejected")]
            if history_reqs:
                with st.expander(f"Riwayat Keputusan Tim ({len(history_reqs)})", expanded=False):
                    for h_req in history_reqs:
                        h_status = h_req.get("status")
                        h_badge = "Disetujui" if h_status == "approved" else "Ditolak"
                        h_color = "#22c55e" if h_status == "approved" else "#ef4444"
                        st.markdown(
                            f"""
                            <div style="padding: 6px 0; border-bottom: 1px solid var(--border-subtle);">
                                <b>{h_req.get('employee_name') or h_req.get('employee_id')}</b> — Cuti {str(h_req.get('leave_type')).capitalize()} ({h_req.get('business_days')} hari) |
                                <span style="color: {h_color}; font-weight: 700;">{h_badge}</span> oleh <code>{h_req.get('reviewed_by', '-')}</code>:
                                <i>"{h_req.get('review_note', '-')}"</i>
                            </div>
                            """,
                            unsafe_allow_html=True,
                        )
                        if h_req.get("leave_type") == "sick" and h_req.get("has_attachment"):
                            h_fn = h_req.get("attachment_filename") or "surat_dokter"
                            with st.expander(f"Tinjau Lampiran Surat Dokter: {h_fn}", expanded=False):
                                h_att = api_request("GET", f"/api/v1/leave-requests/{h_req.get('request_id')}/attachment", token)
                                if h_att:
                                    b64_val = h_att.get("content_base64", "")
                                    raw_bytes = base64.b64decode(b64_val)
                                    c_type = h_att.get("content_type", "")
                                    f_name = h_att.get("filename", h_fn)
                                    if c_type in ("image/png", "image/jpeg"):
                                        st.image(raw_bytes, caption=f_name, use_container_width=True)
                                        st.download_button(
                                            "Unduh Gambar",
                                            data=raw_bytes,
                                            file_name=f_name,
                                            mime=c_type,
                                            key=f"dl_hist_img_{h_req.get('request_id')}",
                                        )
                                    elif c_type == "application/pdf":
                                        st.markdown(
                                            f'<iframe src="data:application/pdf;base64,{b64_val}" width="100%" height="450px" style="border: 1px solid var(--border-subtle); border-radius: 8px;"></iframe>',
                                            unsafe_allow_html=True,
                                        )
                                        st.download_button(
                                            "Unduh PDF",
                                            data=raw_bytes,
                                            file_name=f_name,
                                            mime="application/pdf",
                                            key=f"dl_hist_pdf_{h_req.get('request_id')}",
                                        )
