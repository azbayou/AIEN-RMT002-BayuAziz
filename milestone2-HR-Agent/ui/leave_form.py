"""Interactive leave application form and modal dialog."""
from __future__ import annotations

import base64
from datetime import date, timedelta

import streamlit as st

from ui.policy_rag import (
    get_annual_leave_entitlement_from_policy,
    get_annual_leave_lead_days_from_policy,
    get_min_start_date,
    get_parental_leave_policy_summary,
    get_sick_leave_doc_threshold_from_policy,
)


def render_leave_form() -> None:
    """Interactive leave application form with policy guardrails and live validations."""
    today = date.today()
    active_persona = st.session_state.get("active_persona") or {}
    token = active_persona.get("demo_token", "")

    leave_options = {
        "Cuti Tahunan": "annual",
        "Cuti Sakit": "sick",
        "Cuti Orang Tua": "parental",
    }

    leave_label = st.selectbox(
        "Pilih Jenis Cuti:",
        options=list(leave_options.keys()),
        key="dlg_leave_type_select",
        help="Pilih kategori cuti yang ingin diajukan sesuai hak Anda.",
    )
    leave_type = leave_options[leave_label]

    min_start = get_min_start_date(leave_type, today, token)

    # Sanitize session state if switching leave types changed the minimum date
    current_start = st.session_state.get("dlg_start_date")
    if current_start is not None and current_start < min_start:
        st.session_state["dlg_start_date"] = min_start

    col_d1, col_d2 = st.columns(2)
    with col_d1:
        start_val = st.session_state.get("dlg_start_date", min_start)
        start_date = st.date_input(
            "Tanggal Mulai:",
            value=start_val,
            min_value=min_start,
            key="dlg_start_date",
            help="Tanggal pertama cuti. Tidak bisa memilih sebelum tanggal minimal sesuai kebijakan.",
        )

    # Sanitize end_date relative to start_date
    current_end = st.session_state.get("dlg_end_date")
    if current_end is not None and current_end < start_date:
        st.session_state["dlg_end_date"] = start_date

    with col_d2:
        end_val = st.session_state.get("dlg_end_date", start_date)
        end_date = st.date_input(
            "Tanggal Selesai:",
            value=end_val,
            min_value=start_date,
            key="dlg_end_date",
            help="Tanggal terakhir cuti (minimal sama dengan tanggal mulai).",
        )

    # Calculate business days (Monday-Friday)
    work_days = sum(
        (start_date + timedelta(days=i)).weekday() < 5
        for i in range((end_date - start_date).days + 1)
    )

    # Policy guidelines banner
    if leave_type == "annual":
        lead_days = get_annual_leave_lead_days_from_policy(token)
        entitlement_days = get_annual_leave_entitlement_from_policy(token)
        actual_lead = (start_date - today).days
        st.info(
            f"[ANALISIS KEBIJAKAN HR-LEAVE-001]\n"
            f"- Cuti tahunan wajib diajukan minimal H-{lead_days} ({lead_days} hari) sebelumnya.\n"
            f"- Jarak tanggal mulai pengajuan yang Anda pilih: {actual_lead} hari ke depan.\n"
            f"- Jatah cuti tahunan: {entitlement_days} hari kerja/tahun kalender."
        )
    elif leave_type == "sick":
        sick_thresh = get_sick_leave_doc_threshold_from_policy(token)
        req_att = (work_days > sick_thresh)
        if req_att:
            st.warning(
                f"[KETENTUAN DOKUMEN HR-LEAVE-002]\n"
                f"- Permohonan diajukan untuk {work_days} hari kerja.\n"
                f"- Cuti sakit lebih dari {sick_thresh} hari kerja berturut-turut mewajibkan surat keterangan dokter "
                f"yang diserahkan langsung melalui sistem HR (bukan via chat asisten)."
            )
        else:
            st.info(
                f"[KETENTUAN CUTI SAKIT HR-LEAVE-002]\n"
                f"- Permohonan diajukan untuk {work_days} hari kerja.\n"
                f"- Surat dokter tidak diwajibkan untuk durasi hingga {sick_thresh} hari kerja (opsional).\n"
                f"- Kerahasiaan medis terjamin, asisten tidak mencatat diagnosis detail."
            )
        uploaded_doc = st.file_uploader(
            f"Lampirkan Surat Dokter / Dokumen Pendukung ({'Wajib' if req_att else 'Opsional'} — PDF, PNG, JPG Maks 5 MB):",
            type=["pdf", "png", "jpg", "jpeg"],
            key="dlg_sick_doc_uploader",
        )
        if uploaded_doc is not None:
            ctype = uploaded_doc.type or ""
            if not ctype or ctype == "image/jpg":
                if uploaded_doc.name.lower().endswith(".pdf"):
                    ctype = "application/pdf"
                elif uploaded_doc.name.lower().endswith(".png"):
                    ctype = "image/png"
                else:
                    ctype = "image/jpeg"
            st.session_state["pending_sick_attachment"] = {
                "filename": uploaded_doc.name,
                "content_type": ctype,
                "content_base64": base64.b64encode(uploaded_doc.getvalue()).decode("ascii"),
            }
            st.caption(f"Dokumen {uploaded_doc.name} siap dilampirkan.")
    elif leave_type == "parental":
        parental_info = get_parental_leave_policy_summary(token)
        elig_text = parental_info.get("eligibility", "Berlaku bagi pegawai tetap dengan masa kerja minimal 6 bulan.")
        proc_text = parental_info.get("process", "Permohonan akan diverifikasi lebih lanjut oleh tim HR.")
        st.info(
            f"[KEBIJAKAN CUTI ORANG TUA HR-LEAVE-003]\n"
            f"- {elig_text}\n"
            f"- {proc_text}"
        )

    reason = st.text_area(
        "Alasan / Keterangan Pengajuan (opsional):",
        placeholder="Contoh: Keperluan keluarga mendesak / Pemulihan kesehatan",
        max_chars=300,
        key="dlg_reason_text",
    )

    if work_days == 0:
        st.error("Rentang tanggal yang dipilih tidak memiliki hari kerja (hanya akhir pekan). Silakan pilih tanggal kerja.")
    else:
        st.success(f"Total Durasi: {work_days} hari kerja (Senin s/d Jumat).")

    col_btn_sub, col_btn_can = st.columns([1.3, 1])
    with col_btn_sub:
        can_submit = (work_days > 0)
        if st.button("Ajukan Permohonan Cuti", type="primary", use_container_width=True, disabled=not can_submit):
            sick_thresh = get_sick_leave_doc_threshold_from_policy(token)
            if leave_type == "sick" and work_days > sick_thresh and not st.session_state.get("pending_sick_attachment"):
                st.error(f"[DOKUMEN WAJIB] Sesuai kebijakan HR-LEAVE-002, cuti sakit lebih dari {sick_thresh} hari kerja berturut-turut mewajibkan unggah dokumen surat keterangan dokter di atas.")
            else:
                reason_clean = reason.strip() if reason else ""
                reason_param = f" dengan alasan: {reason_clean}" if reason_clean else ""
                prompt = f"Siapkan {leave_label.lower()} ({leave_type}) dari {start_date.isoformat()} sampai {end_date.isoformat()}{reason_param}"
                st.session_state["prompt_input"] = prompt
                st.session_state["show_leave_modal"] = False
                st.rerun()

    with col_btn_can:
        if st.button("Batal", use_container_width=True):
            st.session_state["show_leave_modal"] = False
            st.rerun()


if hasattr(st, "dialog"):
    @st.dialog("Formulir Pengajuan Cuti", width="medium")
    def leave_dialog():
        render_leave_form()
else:
    def leave_dialog():
        st.session_state["show_leave_modal"] = True
