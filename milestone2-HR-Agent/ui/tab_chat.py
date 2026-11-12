"""Interactive AI Chat Tab with Claude styling, floating action chips, slide-over proposal drawer, and policy citations."""
from __future__ import annotations

import base64
import hashlib
import html
import os
import time
import uuid

import streamlit as st

from ui.api_client import api_request
from ui.config import MIYO_LOGO
from ui.icons import svg_icon
from ui.leave_form import leave_dialog, render_leave_form
from ui.policy_rag import get_sick_leave_doc_threshold_from_policy, has_leave_intent
from ui_contract import API_PATHS


def render_tab_chat(token: str, persona: dict, is_manager: bool, is_admin: bool) -> None:
    """Render Tab 1: Conversational Chat Interface with Claude Warmth & Linear Precision."""
    # Fallback container for leave form if running on older Streamlit without native modal dialog
    if not hasattr(st, "dialog") and st.session_state.get("show_leave_modal", False):
        with st.container():
            st.markdown("### Formulir Pengajuan Cuti")
            render_leave_form()
            st.markdown("---")

    # Dynamic recommended queries based on role
    quick_queries = [
        "Berapa sisa saldo cuti saya saat ini?",
        "Apa syarat cuti sakit lebih dari 2 hari?",
        "Berapa jatah cuti tahunan dan syarat pengajuannya?",
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

    # Welcome greeting with recommendation cards when chat is empty
    welcome_placeholder = st.empty()
    if not st.session_state["chat_history"] and not st.session_state.get("pending_assistant_query"):
        with welcome_placeholder.container():
            user_display = persona.get("label", "").split("—")[0].strip() or "Pegawai"
            st.markdown(
                f"""
                <div style="background-color: var(--bg-surface-elevated); border: 1px solid var(--border-subtle); border-radius: 14px; padding: 22px 24px; margin-bottom: 20px;">
                    <div style="display: flex; align-items: center; gap: 8px; font-size: 0.76rem; text-transform: uppercase; letter-spacing: 0.08em; color: var(--accent-orange); font-weight: 700; margin-bottom: 6px;">
                        {svg_icon("sparkles", size=16, color="var(--accent-orange)")}
                        <span>Asisten Kebijakan HR Digital</span>
                    </div>
                    <div style="font-size: 1.35rem; font-weight: 700; color: var(--text-primary); margin-bottom: 6px; letter-spacing: -0.02em;">
                        Halo, {user_display}
                    </div>
                    <div style="font-size: 0.92rem; color: var(--text-secondary); line-height: 1.6; margin-bottom: 16px;">
                        Saya Miyo, mitra kecerdasan buatan resmi PT Nusantara Digital. Saya siap membantu Anda menelusuri kebijakan perusahaan, memeriksa hak dan saldo cuti, serta memproses pengajuan cuti secara aman dan terverifikasi.
                    </div>
                    <div style="font-size: 0.78rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.08em; color: var(--text-muted); margin-bottom: 10px;">
                        Rekomendasi Pertanyaan Cepat:
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )

            cols_q = st.columns(2)
            for idx_q, q in enumerate(quick_queries[:4]):
                with cols_q[idx_q % 2]:
                    if st.button(q, key=f"btn_chat_quick_card_{idx_q}", use_container_width=True, type="secondary"):
                        # Langsung masukkan pertanyaan ke riwayat chat & kosongkan bubble seketika
                        st.session_state["chat_history"].append({"role": "user", "content": q})
                        st.session_state["pending_assistant_query"] = q
                        welcome_placeholder.empty()
                        st.rerun()

    # Render past conversation history (Pesan user rata kanan tanpa avatar)
    assistant_avatar = MIYO_LOGO if os.path.exists(MIYO_LOGO) else None
    for idx, entry in enumerate(st.session_state["chat_history"]):
        role = entry["role"]
        if role == "user":
            user_escaped = html.escape(entry["content"])
            st.markdown(
                f"""
                <div class="user-chat-bubble-container">
                    <div class="user-chat-bubble">{user_escaped}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )
        else:
            with st.chat_message("assistant", avatar=assistant_avatar):
                st.markdown(entry["content"])

            # Verified Policy Citations (Claude styled cards)
            if entry.get("citations"):
                with st.expander(f"Sumber Kebijakan Terverifikasi ({len(entry['citations'])})", expanded=False):
                    for cite in entry["citations"]:
                        st.markdown(
                            f"""
                            <div class="citation-card">
                                <div class="citation-header">[{cite['document_id']}] {cite['title']} — {cite['section']}</div>
                                <div style="color: var(--text-secondary); margin-top: 4px; line-height: 1.5; font-size: 0.88rem;">
                                    "{cite['excerpt']}"
                                </div>
                            </div>
                            """,
                            unsafe_allow_html=True,
                        )

            # Action proposals presented in Slide-Over Sheet Drawer style
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
                    # Slide-Over Sheet Drawer style container
                    st.markdown(
                        f"""
                        <div class="slide-over-sheet">
                            <div class="proposal-banner-title">
                                {svg_icon('sparkles', size=16, color='var(--accent-orange)')}
                                <span>Proposal Pengajuan Cuti (Menunggu Konfirmasi)</span>
                            </div>
                            <div class="proposal-grid-meta">
                                <div class="proposal-meta-item">
                                    <div class="proposal-meta-label">Jenis Cuti</div>
                                    <div class="proposal-meta-val">{proposal['leave_type'].capitalize()}</div>
                                </div>
                                <div class="proposal-meta-item">
                                    <div class="proposal-meta-label">Periode Tanggal</div>
                                    <div class="proposal-meta-val">{proposal['start_date']} s/d {proposal['end_date']}</div>
                                </div>
                                <div class="proposal-meta-item">
                                    <div class="proposal-meta-label">Durasi Hari Kerja</div>
                                    <div class="proposal-meta-val" style="color: var(--accent-orange);">{proposal['business_days']} Hari Kerja</div>
                                </div>
                                <div class="proposal-meta-item">
                                    <div class="proposal-meta-label">Alasan</div>
                                    <div class="proposal-meta-val">{proposal.get('reason') or 'Tidak dicantumkan'}</div>
                                </div>
                            </div>
                            <div style="font-size: 0.78rem; color: var(--text-muted); margin-bottom: 12px; font-family: var(--font-mono);">
                                ID Proposal: {prop_id} · Batas Konfirmasi: {proposal['expires_at'][:19].replace('T', ' ')} UTC
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

            # Technical details in collapsed expander
            if entry.get("trace_id"):
                with st.expander("Audit Jejak Telemetri", expanded=False):
                    trace_col1, trace_col2 = st.columns(2)
                    with trace_col1:
                        st.caption(f"**Outcome:** `{entry.get('outcome')}`")
                        st.caption(f"**Trace ID:** `{entry.get('trace_id')}`")
                    with trace_col2:
                        usage = entry.get("usage", {})
                        st.caption(f"**Latency:** {usage.get('latency_ms', 0)} ms")
                        st.caption(f"**Tokens:** {usage.get('input_tokens', 0)} in / {usage.get('output_tokens', 0)} out")

    # Tombol Hapus Chat di pojok kanan bawah dekat tombol enter dan mikrofon (hanya muncul saat ada riwayat chat)
    if st.session_state["chat_history"]:
        _, col_clear = st.columns([6.6, 1.4])
        with col_clear:
            if st.button("Hapus Chat", key="btn_clear_chat", icon=":material/delete_outline:", use_container_width=True, type="secondary"):
                st.session_state["chat_history"] = []
                st.session_state["confirmed_proposals"] = set()
                st.rerun()

    # Chat Input Box with native Voice Input (Pinned to the bottom of the viewport)
    default_prompt = st.session_state.pop("prompt_input", "")
    user_input = st.chat_input(
        "Tanyakan kebijakan, aturan kerja, atau ajukan cuti Anda...",
        accept_audio=True,
    )

    prompt_to_send = None
    if user_input is not None:
        if getattr(user_input, "audio", None) is not None:
            raw_bytes = user_input.audio.getvalue()
            mime_type = getattr(user_input.audio, "type", "audio/wav") or "audio/wav"
            ext = "webm" if "webm" in str(mime_type).lower() or raw_bytes.startswith(b"\x1a\x45\xdf\xa3") else "wav"
            filename = f"voice_query.{ext}"

            with st.spinner("Menerjemahkan rekaman suara ke teks..."):
                b64_str = base64.b64encode(raw_bytes).decode("ascii")
                stt_res = api_request(
                    "POST",
                    "/api/v1/audio/transcribe",
                    token,
                    json={
                        "audio_base64": b64_str,
                        "filename": filename,
                        "language": "id",
                    },
                )
            if stt_res and stt_res.get("text"):
                prompt_to_send = stt_res["text"]
            else:
                st.warning("Tidak ada ucapan terdeteksi atau rekaman suara kosong.")
        elif getattr(user_input, "text", None):
            prompt_to_send = user_input.text
        elif isinstance(user_input, str):
            prompt_to_send = user_input

    # Cek query tertunda dari klik bubble rekomendasi ATAU input baru dari chat bar
    pending_query = st.session_state.pop("pending_assistant_query", None)
    query_to_send = None

    if pending_query:
        query_to_send = pending_query
    elif prompt_to_send:
        st.session_state["chat_history"].append({"role": "user", "content": prompt_to_send})
        welcome_placeholder.empty()
        user_escaped = html.escape(prompt_to_send)
        st.markdown(
            f"""
            <div class="user-chat-bubble-container">
                <div class="user-chat-bubble">{user_escaped}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        query_to_send = prompt_to_send

    if query_to_send:
        # Call FastAPI Backend
        assistant_avatar = MIYO_LOGO if os.path.exists(MIYO_LOGO) else None
        with st.chat_message("assistant", avatar=assistant_avatar):
            with st.spinner("Miyo sedang menelusuri kebijakan resmi dan memverifikasi data..."):
                recent_history = []
                for h in st.session_state["chat_history"][:-1][-6:]:
                    if h.get("role") in ("user", "assistant") and h.get("content"):
                        recent_history.append({"role": h["role"], "content": h["content"]})
                payload = {"message": query_to_send, "history": recent_history}
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
