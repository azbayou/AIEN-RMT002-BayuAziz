"""Interactive AI Chat Tab with policy citations, action proposals, and voice input."""
from __future__ import annotations

import base64
import hashlib
import os
import time
import uuid

import streamlit as st

from ui.api_client import api_request
from ui.config import MIYO_LOGO
from ui.leave_form import leave_dialog, render_leave_form
from ui.policy_rag import get_sick_leave_doc_threshold_from_policy, has_leave_intent
from ui_contract import API_PATHS


def render_tab_chat(token: str, persona: dict, is_manager: bool, is_admin: bool) -> None:
    """Render Tab 1: Conversational Chat Interface."""
    # Fallback container for leave form if running on older Streamlit without native modal dialog
    if not hasattr(st, "dialog") and st.session_state.get("show_leave_modal", False):
        with st.container():
            st.markdown("### Formulir Pengajuan Cuti")
            render_leave_form()
            st.markdown("---")

    # Dynamic recommended questions based on user role
    quick_queries = [
        "Berapa jatah cuti tahunan dan syarat pengajuannya?",
        "Berapa sisa saldo cuti saya saat ini?",
        "Kapan surat dokter diwajibkan untuk cuti sakit?",
        "Berapa hari boleh Work From Home (WFH) per minggu?",
    ]
    if is_manager:
        quick_queries.extend([
            "Bagaimana tren analitik dan pengajuan cuti tim saya saat ini?",
            "Siapa anggota tim yang sisa saldo cutinya paling rendah?",
        ])
    elif is_admin:
        quick_queries.extend([
            "Bagaimana status kesehatan telemetri dan kepatuhan sistem?",
            "Bagaimana analitik agregat SDM dan utilisasi cuti?",
        ])

    # Welcome greeting with recommendation questions when chat is empty
    if not st.session_state["chat_history"]:
        user_display = persona.get("label", "").split("—")[0].strip() or "Pegawai"
        st.markdown(
            f"""
            <div style="background-color: var(--bg-surface-elevated); border: 1px solid var(--border-subtle); border-radius: 12px; padding: 20px 22px; margin-bottom: 18px;">
                <div style="font-size: 0.78rem; text-transform: uppercase; letter-spacing: 0.08em; color: var(--accent-sky); font-weight: 700; margin-bottom: 4px;">
                    Asisten Kebijakan HR Digital
                </div>
                <div style="font-size: 1.25rem; font-weight: 800; color: var(--text-primary); margin-bottom: 6px;">
                    Halo, {user_display}
                </div>
                <div style="font-size: 0.9rem; color: var(--text-secondary); line-height: 1.5; margin-bottom: 14px;">
                    Saya Miyo, mitra kecerdasan buatan resmi PT Nusantara Digital. Saya siap membantu Anda menelusuri kebijakan perusahaan, memeriksa hak & saldo cuti, serta memproses pengajuan cuti bergaransi keamanan.
                </div>
                <div style="font-size: 0.82rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.06em; color: var(--accent-sky); margin-bottom: 8px;">
                    Rekomendasi Pertanyaan:
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        cols_q = st.columns(2)
        for idx_q, q in enumerate(quick_queries):
            with cols_q[idx_q % 2]:
                if st.button(q, key=f"btn_chat_quick_card_{idx_q}", use_container_width=True, type="secondary"):
                    st.session_state["prompt_input"] = q
                    st.rerun()

    # Render past conversation history
    assistant_avatar = MIYO_LOGO if os.path.exists(MIYO_LOGO) else None
    for idx, entry in enumerate(st.session_state["chat_history"]):
        role = entry["role"]
        avatar = None if role == "user" else assistant_avatar
        with st.chat_message(role, avatar=avatar):
            st.markdown(entry["content"])

            # Verified Policy Citations
            if entry.get("citations"):
                with st.expander(f"Sumber Kebijakan Terverifikasi ({len(entry['citations'])})", expanded=False):
                    for cite in entry["citations"]:
                        st.markdown(
                            f"""
                            <div class="citation-card">
                                <div class="citation-header">[{cite['document_id']}] {cite['title']} — {cite['section']}</div>
                                <div class="citation-body">"{cite['excerpt']}"</div>
                            </div>
                            """,
                            unsafe_allow_html=True,
                        )

            # Action proposals (supports multiple proposals per turn)
            proposals_list = entry.get("action_proposals") or (
                [entry.get("action_proposal")] if entry.get("action_proposal") else []
            )
            unconfirmed_proposals = [p for p in proposals_list if p["proposal_id"] not in st.session_state["confirmed_proposals"]]
            if len(unconfirmed_proposals) > 1:
                st.info(f"Ditemukan **{len(unconfirmed_proposals)} proposal permohonan cuti**. Anda dapat mengonfirmasi satu per satu di bawah atau sekaligus:")
                if st.button(f"Konfirmasi Semua ({len(unconfirmed_proposals)} Pengajuan Cuti Sekaligus)", key=f"btn_confirm_all_{idx}", type="primary"):
                    sick_thresh = get_sick_leave_doc_threshold_from_policy(token)
                    missing_sick = any(
                        (up.get("requires_attachment") or (up.get("leave_type") == "sick" and up.get("business_days", 0) > sick_thresh))
                        and not (st.session_state.get(f"pending_sick_att_{up['proposal_id']}") or st.session_state.get("pending_sick_attachment"))
                        for up in unconfirmed_proposals
                    )
                    if missing_sick:
                        st.error(f"[DOKUMEN BELUM LENGKAP] Terdapat permohonan cuti sakit (> {sick_thresh} hari kerja) yang belum memiliki bukti surat dokter. Silakan unggah surat dokter pada kartu proposal terkait sebelum mengonfirmasi.")
                    else:
                        with st.spinner("Mengonfirmasi seluruh pengajuan cuti..."):
                            all_ok = True
                            for up in unconfirmed_proposals:
                                u_prop_id = up["proposal_id"]
                                idem_key = f"idem_{u_prop_id}"
                                st.session_state.setdefault(idem_key, str(uuid.uuid4()))
                                confirmed = api_request(
                                    "POST",
                                    API_PATHS["confirm"].format(proposal_id=u_prop_id),
                                    token,
                                    json={"idempotency_key": st.session_state[idem_key]},
                                )
                                if confirmed:
                                    st.session_state["confirmed_proposals"].add(u_prop_id)
                                    u_att = st.session_state.pop(f"pending_sick_att_{u_prop_id}", None) or st.session_state.pop("pending_sick_attachment", None)
                                    if u_att:
                                        api_request("POST", f"/api/v1/leave-requests/{confirmed['request_id']}/attachment", token, json=u_att)
                                else:
                                    all_ok = False
                            if all_ok:
                                st.success(f"[BERHASIL] Seluruh {len(unconfirmed_proposals)} proposal berhasil dikonfirmasi dan dikirim ke Manager Review.")
                                time.sleep(1)
                                st.rerun()

            for proposal in proposals_list:
                prop_id = proposal["proposal_id"]
                is_confirmed = prop_id in st.session_state["confirmed_proposals"]

                if is_confirmed:
                    st.success(f"[TERKONFIRMASI] Permintaan {prop_id} ({proposal['leave_type'].capitalize()}: {proposal['start_date']} s/d {proposal['end_date']}) telah dikonfirmasi dan berstatus pending_manager_review.")
                else:
                    st.markdown(
                        f"""
                        <div class="proposal-box">
                            <div class="proposal-title">Proposal Permohonan Cuti (Menunggu Konfirmasi)</div>
                            <div class="proposal-detail"><b>Jenis Cuti:</b> {proposal['leave_type'].capitalize()}</div>
                            <div class="proposal-detail"><b>Rentang Tanggal:</b> {proposal['start_date']} s/d {proposal['end_date']} (<b>{proposal['business_days']} hari kerja</b>)</div>
                            <div class="proposal-detail"><b>Alasan:</b> {proposal.get('reason') or 'Tidak dicantumkan'}</div>
                            <div>
                                {''.join([f'<span class="validation-badge">{v}</span>' for v in proposal.get('validation_summary', [])])}
                                <span class="expiry-tag">Batas Konfirmasi: {proposal['expires_at'][:19].replace('T', ' ')} UTC</span>
                            </div>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )

                    card_doc = None
                    if proposal.get("leave_type") == "sick":
                        sick_thresh = get_sick_leave_doc_threshold_from_policy(token)
                        b_days = proposal.get("business_days", 0)
                        req_att = proposal.get("requires_attachment") if proposal.get("requires_attachment") is not None else (b_days > sick_thresh)

                        if req_att:
                            st.warning(f"[DOKUMEN WAJIB] Sesuai kebijakan cuti sakit HR-LEAVE-002, cuti sakit lebih dari {sick_thresh} hari kerja berturut-turut wajib melampirkan foto/dokumen surat keterangan dokter di bawah ini sebelum mengonfirmasi permohonan.")
                        else:
                            st.info(f"[INFORMASI] Cuti sakit {b_days} hari kerja tidak mewajibkan surat dokter (surat dokter hanya wajib jika cuti sakit lebih dari {sick_thresh} hari kerja berturut-turut). Lampiran di bawah ini bersifat opsional.")

                        pending_att = st.session_state.get(f"pending_sick_att_{prop_id}") or st.session_state.get("pending_sick_attachment")
                        if pending_att:
                            st.success(f"File surat dokter siap dilampirkan: {pending_att['filename']}")
                        card_doc = st.file_uploader(
                            f"Unggah Bukti Foto / Surat Dokter ({'Wajib' if req_att else 'Opsional'} — JPG, PNG, PDF Maks 5 MB):",
                            type=["pdf", "png", "jpg", "jpeg"],
                            key=f"card_sick_uploader_{prop_id}",
                        )
                        if card_doc is not None:
                            ctype = card_doc.type or ""
                            if not ctype or ctype == "image/jpg":
                                if card_doc.name.lower().endswith(".pdf"):
                                    ctype = "application/pdf"
                                elif card_doc.name.lower().endswith(".png"):
                                    ctype = "image/png"
                                else:
                                    ctype = "image/jpeg"
                            st.session_state[f"pending_sick_att_{prop_id}"] = {
                                "filename": card_doc.name,
                                "content_type": ctype,
                                "content_base64": base64.b64encode(card_doc.getvalue()).decode("ascii"),
                            }
                            st.session_state["pending_sick_attachment"] = st.session_state[f"pending_sick_att_{prop_id}"]
                            st.caption(f"Dokumen {card_doc.name} dipilih.")

                    col_btn1, col_btn2, _ = st.columns([1.3, 1.4, 2.5])
                    with col_btn1:
                        confirm_key = f"btn_confirm_{prop_id}"
                        if st.button("Konfirmasi Pengajuan", key=confirm_key, type="primary"):
                            att_to_upload = st.session_state.get(f"pending_sick_att_{prop_id}") or st.session_state.get("pending_sick_attachment")
                            sick_thresh = get_sick_leave_doc_threshold_from_policy(token)
                            b_days = proposal.get("business_days", 0)
                            req_att = proposal.get("requires_attachment") if proposal.get("requires_attachment") is not None else (b_days > sick_thresh)
                            if proposal.get("leave_type") == "sick" and req_att and not att_to_upload and card_doc is None:
                                st.error(f"[DOKUMEN WAJIB] Sesuai kebijakan HR-LEAVE-002, cuti sakit lebih dari {sick_thresh} hari kerja berturut-turut wajib mengunggah foto atau dokumen surat keterangan dokter di atas sebelum mengonfirmasi permohonan.")
                            else:
                                idem_key = f"idem_{prop_id}"
                                st.session_state.setdefault(idem_key, str(uuid.uuid4()))
                                with st.spinner("Mengonfirmasi dan mengunci request..."):
                                    confirmed = api_request(
                                        "POST",
                                        API_PATHS["confirm"].format(proposal_id=prop_id),
                                        token,
                                        json={"idempotency_key": st.session_state[idem_key]},
                                    )
                                if confirmed:
                                    req_id = confirmed["request_id"]
                                    st.session_state["confirmed_proposals"].add(prop_id)
                                    st.success(
                                        f"[BERHASIL] Permintaan cuti #{req_id} berhasil diajukan dengan status {confirmed['status']}."
                                    )
                                    pending_att = st.session_state.pop(f"pending_sick_att_{prop_id}", None) or st.session_state.pop("pending_sick_attachment", None)
                                    if pending_att:
                                        with st.spinner("Mengunggah lampiran surat dokter..."):
                                            att_res = api_request(
                                                "POST",
                                                f"/api/v1/leave-requests/{req_id}/attachment",
                                                token,
                                                json=pending_att,
                                            )
                                        if att_res:
                                            st.success(f"Surat dokter {pending_att['filename']} berhasil dilampirkan.")
                                        else:
                                            st.warning("Permintaan cuti berhasil, namun gagal mengunggah surat dokter. Anda dapat menyusulkannya di tab Permintaan Cuti Saya.")
                                    time.sleep(1)
                                    st.rerun()
                    with col_btn2:
                        if st.button("Ubah via Formulir", key=f"btn_edit_prop_{prop_id}", type="secondary"):
                            if hasattr(st, "dialog"):
                                leave_dialog()
                            else:
                                st.session_state["show_leave_modal"] = True
                                st.rerun()

            # If dialogue expresses intent to request leave and proposal is not yet generated
            if entry["role"] == "assistant" and not is_admin and not proposals_list:
                prev_user_msg = (
                    st.session_state["chat_history"][idx - 1].get("content", "")
                    if idx > 0 and st.session_state["chat_history"][idx - 1].get("role") == "user"
                    else ""
                )
                if has_leave_intent(prev_user_msg) or has_leave_intent(entry.get("content", "")):
                    st.markdown(
                        """
                        <div style="background-color: var(--bg-surface-elevated); border: 1px solid var(--border-subtle); border-radius: 10px; padding: 12px 16px; margin-top: 10px; margin-bottom: 8px;">
                            <div style="font-weight: 700; color: var(--accent-sky); font-size: 0.95rem; margin-bottom: 2px;">
                                Formulir Permohonan Cuti
                            </div>
                            <div style="font-size: 0.83rem; color: var(--text-secondary);">
                                Ingin langsung mengajukan cuti? Klik tombol di bawah untuk memilih tanggal via kalender interaktif, atau Anda dapat mengetik permohonan secara manual di kolom chat.
                            </div>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )
                    col_form_btn, _ = st.columns([1.5, 2.5])
                    with col_form_btn:
                        if st.button("Buka Formulir Pengajuan Cuti", key=f"btn_form_chat_{idx}", type="primary"):
                            if hasattr(st, "dialog"):
                                leave_dialog()
                            else:
                                st.session_state["show_leave_modal"] = True
                                st.rerun()

            # Technical details in collapsed expander
            if entry.get("trace_id"):
                with st.expander("Trace & Telemetry Audit", expanded=False):
                    trace_col1, trace_col2 = st.columns(2)
                    with trace_col1:
                        st.caption(f"**Outcome:** `{entry.get('outcome')}`")
                        st.caption(f"**Trace ID:** `{entry.get('trace_id')}`")
                    with trace_col2:
                        usage = entry.get("usage", {})
                        st.caption(f"**Latency:** {usage.get('latency_ms', 0)} ms")
                        st.caption(f"**Tokens:** {usage.get('input_tokens', 0)} in / {usage.get('output_tokens', 0)} out")
                    if entry.get("tool_calls"):
                        st.write("**Tool Calls:**")
                        for tc in entry["tool_calls"]:
                            st.caption(f"- `{tc.get('name')}` · Status: `{tc.get('status')}` ({tc.get('duration_ms', 0)} ms)")

    # Chat Action Toolbar (Voice Input, Recommendation Questions, Clear Chat)
    col_voice, col_quick_pop, col_clear = st.columns([1.5, 2.5, 1.2])
    with col_voice:
        with st.popover("Input Suara (Mikrofon)"):
            st.caption("Rekam pertanyaan Anda dalam Bahasa Indonesia. Rekaman diproses langsung di memori dan tidak disimpan.")
            audio_val = st.audio_input("Klik tombol mikrofon untuk mulai/berhenti merekam:", key="voice_chat_input")
            if audio_val is not None:
                raw_bytes = audio_val.getvalue()
                audio_hash = hashlib.sha256(raw_bytes).hexdigest()[:16]
                if st.session_state.get("last_transcribed_hash") != audio_hash:
                    with st.spinner("Menerjemahkan suara ke teks..."):
                        b64_str = base64.b64encode(raw_bytes).decode("ascii")
                        stt_res = api_request(
                            "POST",
                            "/api/v1/audio/transcribe",
                            token,
                            json={
                                "audio_base64": b64_str,
                                "filename": "voice_query.wav",
                                "language": "id",
                            },
                        )
                    st.session_state["last_transcribed_hash"] = audio_hash
                    if stt_res and stt_res.get("text"):
                        detected_text = stt_res["text"]
                        st.session_state["prompt_input"] = detected_text
                        st.success(f"Suara terdeteksi: \"{detected_text}\"")
                        st.rerun()

    with col_quick_pop:
        with st.popover("Rekomendasi Pertanyaan"):
            st.caption("Pilih pertanyaan rekomendasi untuk diajukan:")
            for idx_q, q in enumerate(quick_queries):
                if st.button(q, key=f"btn_chat_quick_pop_{idx_q}", use_container_width=True):
                    st.session_state["prompt_input"] = q
                    st.rerun()

    with col_clear:
        if st.session_state["chat_history"]:
            if st.button("Hapus Chat", key="btn_clear_chat", use_container_width=True):
                st.session_state["chat_history"] = []
                st.session_state["confirmed_proposals"] = set()
                st.rerun()

    # Chat Input Box
    default_prompt = st.session_state.pop("prompt_input", "")
    user_input = st.chat_input("Tanyakan kebijakan, aturan kerja, atau ajukan cuti Anda...")

    # If triggered via quick button or direct chat input
    prompt_to_send = user_input or (default_prompt if default_prompt else None)

    if prompt_to_send:
        # 1. Display User Message
        st.session_state["chat_history"].append({"role": "user", "content": prompt_to_send})
        with st.chat_message("user"):
            st.markdown(prompt_to_send)

        # 2. Call FastAPI Backend
        assistant_avatar = MIYO_LOGO if os.path.exists(MIYO_LOGO) else None
        with st.chat_message("assistant", avatar=assistant_avatar):
            with st.spinner("Miyo sedang menelusuri kebijakan resmi dan memverifikasi data..."):
                recent_history = []
                for h in st.session_state["chat_history"][:-1][-6:]:
                    if h.get("role") in ("user", "assistant") and h.get("content"):
                        recent_history.append({"role": h["role"], "content": h["content"]})
                payload = {"message": prompt_to_send, "history": recent_history}
                result = api_request("POST", API_PATHS["chat"], token, json=payload)

            if result:
                st.markdown(result["answer"])

                # Store assistant response in history
                st.session_state["chat_history"].append(
                    {
                        "role": "assistant",
                        "content": result["answer"],
                        "outcome": result.get("outcome"),
                        "citations": result.get("citations", []),
                        "action_proposal": result.get("action_proposal"),
                        "action_proposals": result.get("action_proposals", []),
                        "tool_calls": result.get("tool_calls", []),
                        "trace_id": result.get("trace_id"),
                        "usage": result.get("usage", {}),
                    }
                )
                st.rerun()
