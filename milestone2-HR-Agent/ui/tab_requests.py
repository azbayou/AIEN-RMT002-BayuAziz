"""My Leave Requests tracker tab with attachment preview and upload."""
from __future__ import annotations

import base64
import time

import streamlit as st

from ui.api_client import api_request
from ui.leave_form import leave_dialog
from ui_contract import API_PATHS


def render_tab_my_requests(token: str, persona: dict, is_admin: bool) -> None:
    """Render Tab 2: Employee's Personal Leave Requests Tracker."""
    st.subheader(f"Daftar Permohonan Cuti: {persona['label']}")
    st.caption("Daftar seluruh pengajuan cuti aktif dan historis milik identitas Anda.")

    col_sync, col_create, _ = st.columns([1, 1.4, 3])
    with col_sync:
        if st.button("Segarkan Data", key="btn_refresh_my_reqs", use_container_width=True):
            st.rerun()
    with col_create:
        if not is_admin:
            if st.button("Buat Pengajuan Baru", key="btn_open_leave_tab2", use_container_width=True, type="primary"):
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
            total_days = sum(item.get("business_days", 0) for item in leave_data)
            pending_count = sum(1 for item in leave_data if item.get("status") == "pending_manager_review")

            m_col1, m_col2, m_col3 = st.columns(3)
            m_col1.metric("Total Permohonan", len(leave_data))
            m_col2.metric("Menunggu Review", pending_count)
            m_col3.metric("Total Hari Kerja", f"{total_days} Hari")

            st.markdown("---")

            for req in leave_data:
                status_raw = req.get("status", "")
                if status_raw == "pending_manager_review":
                    badge_html = '<span class="status-badge-pending">Menunggu Review Manajer</span>'
                elif status_raw == "approved":
                    badge_html = '<span class="status-badge-approved">Disetujui</span>'
                else:
                    badge_html = f'<span class="status-badge-cancelled">{status_raw.upper()}</span>'

                with st.container():
                    st.markdown(
                        f"""
                        <div style="background-color: var(--bg-surface-elevated); border: 1px solid var(--border-subtle); border-radius: 10px; padding: 14px 18px; margin-bottom: 12px;">
                            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
                                <div style="font-weight: 700; font-size: 1.05rem; color: var(--text-primary);">
                                    ID: <code>{req.get('request_id')}</code> — Cuti {req.get('leave_type', '').capitalize()}
                                </div>
                                <div>{badge_html}</div>
                            </div>
                            <div style="color: var(--text-secondary); font-size: 0.92rem;">
                                <b>Periode:</b> {req.get('start_date')} s/d {req.get('end_date')} (<b>{req.get('business_days')} hari kerja</b>)
                            </div>
                            <div style="color: var(--text-muted); font-size: 0.8rem; margin-top: 6px;">
                                Diajukan pada: {req.get('created_at', '')[:19].replace('T', ' ')} UTC
                            </div>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )

                    if req.get("leave_type") == "sick":
                        r_id = req.get("request_id")
                        has_att = req.get("has_attachment", False)
                        if has_att:
                            att_name = req.get("attachment_filename") or "surat_dokter"
                            st.markdown(f"**Lampiran:** `{att_name}`")
                            with st.expander(f"Lihat Lampiran: {att_name}", expanded=False):
                                att_view = api_request("GET", f"/api/v1/leave-requests/{r_id}/attachment", token)
                                if att_view:
                                    b64_str = att_view.get("content_base64", "")
                                    raw_b = base64.b64decode(b64_str)
                                    ct = att_view.get("content_type", "")
                                    if ct in ("image/png", "image/jpeg"):
                                        st.image(raw_b, caption=att_name, use_container_width=True)
                                        st.download_button(
                                            "Unduh Gambar",
                                            data=raw_b,
                                            file_name=att_name,
                                            mime=ct,
                                            key=f"dl_own_img_{r_id}",
                                        )
                                    elif ct == "application/pdf":
                                        st.markdown(
                                            f'<iframe src="data:application/pdf;base64,{b64_str}" width="100%" height="400px" style="border: 1px solid var(--border-subtle); border-radius: 8px;"></iframe>',
                                            unsafe_allow_html=True,
                                        )
                                        st.download_button(
                                            "Unduh PDF",
                                            data=raw_b,
                                            file_name=att_name,
                                            mime="application/pdf",
                                            key=f"dl_own_pdf_{r_id}",
                                        )
                        else:
                            st.warning("Belum ada lampiran surat dokter")

                        if status_raw == "pending_manager_review":
                            with st.expander("Unggah / Perbarui Surat Dokter (PDF / Gambar)"):
                                sub_doc = st.file_uploader(
                                    "Pilih dokumen surat dokter (PDF, PNG, JPG — Maks 5 MB):",
                                    type=["pdf", "png", "jpg", "jpeg"],
                                    key=f"uploader_tab_req_{r_id}",
                                )
                                if sub_doc is not None:
                                    if st.button("Simpan Lampiran", key=f"btn_upload_tab_req_{r_id}", type="primary"):
                                        ctype = sub_doc.type or ""
                                        if not ctype or ctype == "image/jpg":
                                            if sub_doc.name.lower().endswith(".pdf"):
                                                ctype = "application/pdf"
                                            elif sub_doc.name.lower().endswith(".png"):
                                                ctype = "image/png"
                                            else:
                                                ctype = "image/jpeg"
                                        payload = {
                                            "filename": sub_doc.name,
                                            "content_type": ctype,
                                            "content_base64": base64.b64encode(sub_doc.getvalue()).decode("ascii"),
                                        }
                                        with st.spinner("Mengunggah dokumen..."):
                                            res_up = api_request(
                                                "POST",
                                                f"/api/v1/leave-requests/{r_id}/attachment",
                                                token,
                                                json=payload,
                                            )
                                        if res_up:
                                            st.success(f"Surat dokter {sub_doc.name} berhasil disimpan.")
                                            time.sleep(0.5)
                                            st.rerun()
