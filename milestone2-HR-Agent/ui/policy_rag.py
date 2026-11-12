"""Dynamic policy retrieval and rule parsing via RAG and HR Knowledge Base."""
from __future__ import annotations

import re
from datetime import date, timedelta
from pathlib import Path

import httpx
import streamlit as st

from ui.config import API_URL, BASE_DIR


def _fallback_lead_days_from_file() -> int:
    """Fallback cadangan membaca file kebijakan jika API/Agent sedang tidak aktif."""
    try:
        policy_file = BASE_DIR / "data" / "policies" / "annual-leave.md"
        if policy_file.exists():
            text = policy_file.read_text(encoding="utf-8").lower()
            match_h = re.search(r"\bh-(\d+)\b", text)
            if match_h:
                return int(match_h.group(1))
            kata_angka = {"satu": 1, "dua": 2, "tiga": 3, "empat": 4, "lima": 5, "tujuh": 7}
            for word, val in kata_angka.items():
                if f"{word} hari" in text:
                    return val
            match_num = re.search(r"(\d+)\s+hari", text)
            if match_num:
                return int(match_num.group(1))
    except Exception:
        pass
    return 3


@st.cache_data(ttl=120, show_spinner=False)
def _query_agent_for_lead_days(api_url: str, token: str, policy_mtime: float) -> int:
    """Menanyakan langsung ke AI Agent melalui endpoint /chat untuk menganalisis kebijakan resmi via RAG."""
    try:
        query_msg = (
            "Berapa hari minimal pengajuan cuti tahunan sebelum tanggal mulai menurut kebijakan HR? "
            "Sebutkan angka harinya secara jelas."
        )
        answer = ""
        for chat_path in ("/api/v1/chat", "/chat"):
            try:
                resp = httpx.post(
                    f"{api_url}{chat_path}",
                    headers={"Authorization": f"Bearer {token}"},
                    json={"message": query_msg},
                    timeout=20.0,
                )
                if resp.status_code == 200:
                    answer = resp.json().get("answer", "").lower()
                    if answer:
                        break
            except Exception:
                continue

        if answer:
            m_h = re.search(r"\bh-(\d+)\b", answer)
            if m_h:
                return int(m_h.group(1))

            kata_angka = {"satu": 1, "dua": 2, "tiga": 3, "empat": 4, "lima": 5, "tujuh": 7}
            for word, val in kata_angka.items():
                if f"{word} hari" in answer:
                    return val

            m_num = re.search(r"(\d+)\s+hari", answer)
            if m_num:
                return int(m_num.group(1))
    except Exception:
        pass

    return _fallback_lead_days_from_file()


def get_annual_leave_lead_days_from_policy(token: str = "") -> int:
    """Minta Agent AI membaca dan menganalisis batas minimal pengajuan cuti tahunan (H-x) via RAG."""
    if not token:
        active_persona = st.session_state.get("active_persona") or {}
        token = active_persona.get("demo_token", "")

    policy_file = BASE_DIR / "data" / "policies" / "annual-leave.md"
    policy_mtime = policy_file.stat().st_mtime if policy_file.exists() else 0.0

    if token:
        return _query_agent_for_lead_days(API_URL, token, policy_mtime)

    return _fallback_lead_days_from_file()


def _fallback_sick_threshold_from_file() -> int:
    """Fallback cadangan membaca file kebijakan cuti sakit jika API/Agent sedang tidak aktif."""
    try:
        from src.domain import get_sick_leave_doc_threshold
        return get_sick_leave_doc_threshold()
    except Exception:
        return 2


def _fallback_parental_leave_from_file() -> dict[str, str]:
    """Fallback cadangan membaca file kebijakan cuti orang tua [HR-LEAVE-003] jika API/Agent tidak aktif."""
    eligibility = "Berlaku bagi pegawai tetap dengan masa kerja minimal 6 bulan."
    process = "Permohonan akan diverifikasi lebih lanjut oleh tim HR (asisten menyiapkan permintaan dan membuat tiket konsultasi)."
    try:
        policy_file = BASE_DIR / "data" / "policies" / "parental-leave.md"
        if policy_file.exists():
            content = policy_file.read_text(encoding="utf-8")
            m_kel = re.search(r"##\s*Kelayakan\s*\n+([^#]+)", content, re.IGNORECASE)
            if m_kel:
                raw_kel = m_kel.group(1).strip()
                first_sent = raw_kel.split(".")[0].strip()
                if first_sent:
                    eligibility = f"{first_sent}."
                else:
                    eligibility = raw_kel
            m_pro = re.search(r"##\s*Proses\s*\n+([^#]+)", content, re.IGNORECASE)
            if m_pro:
                process = m_pro.group(1).strip()
    except Exception:
        pass

    return {
        "eligibility": eligibility,
        "process": process,
        "tenure": "minimal 6 bulan",
        "verification": "Keputusan kelayakan dan durasi akhir dilakukan manusia dari tim HR",
        "source": "data/policies/parental-leave.md",
    }


@st.cache_data(ttl=120, show_spinner=False)
def get_parental_leave_policy_summary(token: str = "") -> dict[str, str]:
    """Mendapatkan ringkasan kebijakan cuti orang tua [HR-LEAVE-003] via RAG / AI Agent dengan fallback dokumen lokal."""
    if not token:
        try:
            active_persona = st.session_state.get("active_persona") or {}
            token = active_persona.get("demo_token", "")
        except Exception:
            token = ""

    if not token:
        return _fallback_parental_leave_from_file()

    try:
        query_msg = (
            "Menurut kebijakan cuti orang tua [HR-LEAVE-003], apa syarat kelayakan masa kerja pegawai "
            "dan bagaimana proses verifikasi atau pengajuannya? Sebutkan secara ringkas."
        )
        answer = ""
        for chat_path in ("/api/v1/chat", "/chat"):
            try:
                resp = httpx.post(
                    f"{API_URL}{chat_path}",
                    headers={"Authorization": f"Bearer {token}"},
                    json={"message": query_msg},
                    timeout=20.0,
                )
                if resp.status_code == 200:
                    answer = resp.json().get("answer", "").strip()
                    if answer:
                        break
            except Exception:
                continue

        if answer:
            eligibility = ""
            process = ""
            lines = [line.strip().lstrip("-*•123456789. ") for line in answer.split("\n") if line.strip()]
            for line in lines:
                lower_l = line.lower()
                if not eligibility and any(k in lower_l for k in ("kelayakan", "pegawai tetap", "masa kerja", "enam bulan", "6 bulan")):
                    eligibility = line
                elif not process and any(k in lower_l for k in ("proses", "verifikasi", "tiket", "tim hr", "human", "manusia")):
                    process = line

            if not eligibility or not process:
                sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", answer) if s.strip()]
                for s in sentences:
                    lower_s = s.lower()
                    if not eligibility and any(k in lower_s for k in ("kelayakan", "pegawai tetap", "masa kerja", "enam bulan", "6 bulan")):
                        eligibility = s
                    elif not process and any(k in lower_s for k in ("proses", "verifikasi", "tiket", "tim hr", "human", "manusia")):
                        process = s

            fallback_data = _fallback_parental_leave_from_file()
            return {
                "eligibility": eligibility or fallback_data["eligibility"],
                "process": process or fallback_data["process"],
                "tenure": "minimal 6 bulan",
                "verification": "Keputusan kelayakan dan durasi akhir dilakukan manusia dari tim HR",
                "summary": answer,
                "source": "rag_agent",
            }
    except Exception:
        pass

    return _fallback_parental_leave_from_file()


def _fallback_annual_entitlement_from_file() -> int:
    """Fallback cadangan membaca jatah cuti tahunan dari file kebijakan [HR-LEAVE-001]."""
    try:
        policy_file = BASE_DIR / "data" / "policies" / "annual-leave.md"
        if policy_file.exists():
            text = policy_file.read_text(encoding="utf-8").lower()
            m = re.search(r"memperoleh\s+([a-zA-Z0-9]+)\s+hari\s+kerja", text)
            if not m:
                m = re.search(r"([a-zA-Z0-9]+)\s+hari\s+kerja\s+cuti\s+tahunan", text)
            if m:
                raw = m.group(1).lower()
                if raw.isdigit():
                    return int(raw)
                kata_angka = {"sepuluh": 10, "sebelas": 11, "dua belas": 12, "tiga belas": 13, "empat belas": 14}
                if raw in kata_angka:
                    return kata_angka[raw]
    except Exception:
        pass
    return 12


@st.cache_data(ttl=120, show_spinner=False)
def get_annual_leave_entitlement_from_policy(token: str = "") -> int:
    """Mengambil jatah cuti tahunan resmi perusahaan dari kebijakan [HR-LEAVE-001] via RAG / AI Agent."""
    if not token:
        try:
            active_persona = st.session_state.get("active_persona") or {}
            token = active_persona.get("demo_token", "")
        except Exception:
            token = ""

    if not token:
        return _fallback_annual_entitlement_from_file()

    try:
        query_msg = (
            "Menurut kebijakan cuti tahunan [HR-LEAVE-001], berapa hari kerja jatah cuti tahunan "
            "per tahun kalender bagi pegawai tetap? Sebutkan angka harinya secara jelas."
        )
        answer = ""
        for chat_path in ("/api/v1/chat", "/chat"):
            try:
                resp = httpx.post(
                    f"{API_URL}{chat_path}",
                    headers={"Authorization": f"Bearer {token}"},
                    json={"message": query_msg},
                    timeout=20.0,
                )
                if resp.status_code == 200:
                    answer = resp.json().get("answer", "").lower()
                    if answer:
                        break
            except Exception:
                continue

        if answer:
            m_num = re.search(r"(\d+)\s+hari\s+kerja", answer)
            if not m_num:
                m_num = re.search(r"(\d+)\s+hari", answer)
            if m_num:
                val = int(m_num.group(1))
                if 1 <= val <= 365:
                    return val

            kata_angka = {
                "dua belas": 12,
                "sebelas": 11,
                "sepuluh": 10,
                "tiga belas": 13,
                "empat belas": 14,
                "lima belas": 15,
            }
            for word, val in kata_angka.items():
                if word in answer:
                    return val
    except Exception:
        pass

    return _fallback_annual_entitlement_from_file()


@st.cache_data(ttl=120, show_spinner=False)
def _query_agent_for_sick_threshold(api_url: str, token: str, policy_mtime: float) -> int:
    """Menanyakan langsung ke AI Agent melalui endpoint /chat untuk menganalisis kebijakan cuti sakit via RAG."""
    try:
        query_msg = (
            "Menurut kebijakan cuti sakit [HR-LEAVE-002], berapa batas maksimal hari kerja berturut-turut tanpa memerlukan surat dokter? "
            "Sebutkan angka harinya secara jelas."
        )
        answer = ""
        for chat_path in ("/api/v1/chat", "/chat"):
            try:
                resp = httpx.post(
                    f"{api_url}{chat_path}",
                    headers={"Authorization": f"Bearer {token}"},
                    json={"message": query_msg},
                    timeout=20.0,
                )
                if resp.status_code == 200:
                    answer = resp.json().get("answer", "").lower()
                    if answer:
                        break
            except Exception:
                continue

        if answer:
            m_more = re.search(r"lebih\s+dari\s+([a-zA-Z0-9]+)\s+hari", answer)
            if m_more:
                raw = m_more.group(1)
                kata_angka = {"satu": 1, "dua": 2, "tiga": 3, "empat": 4, "lima": 5, "tujuh": 7}
                if raw.isdigit():
                    return int(raw)
                if raw in kata_angka:
                    return kata_angka[raw]

            kata_angka = {"satu": 1, "dua": 2, "tiga": 3, "empat": 4, "lima": 5, "tujuh": 7}
            for word, val in kata_angka.items():
                if f"{word} hari" in answer:
                    return val

            m_num = re.search(r"(\d+)\s+hari", answer)
            if m_num:
                return int(m_num.group(1))
    except Exception:
        pass

    return _fallback_sick_threshold_from_file()


def get_sick_leave_doc_threshold_from_policy(token: str = "") -> int:
    """Minta Agent AI membaca dan menganalisis kebijakan cuti sakit via RAG (search_hr_policy di PostgreSQL)."""
    if not token:
        active_persona = st.session_state.get("active_persona") or {}
        token = active_persona.get("demo_token", "")

    policy_file = BASE_DIR / "data" / "policies" / "sick-leave.md"
    policy_mtime = policy_file.stat().st_mtime if policy_file.exists() else 0.0

    if token:
        return _query_agent_for_sick_threshold(API_URL, token, policy_mtime)

    return _fallback_sick_threshold_from_file()


def has_leave_intent(text: str) -> bool:
    """Mendeteksi apakah pesan pengguna atau dialog memuat niat pengajuan/permohonan cuti."""
    if not text:
        return False
    lower = text.lower()
    intent_keywords = [
        r"\b(?:mau|ingin|minta|request|ajukan|pengajuan|siapkan|buat|ambil|butuh|rencana)\s+.*cuti\b",
        r"\b(?:permohonan|pengajuan)\s+cuti\b",
        r"\bsiap(?:kan)?\s+cuti\b",
        r"\bcuti\b.*(?:ajukan|request|ambil|minta|butuh|mau|ingin|rencana)",
    ]
    return any(re.search(p, lower) for p in intent_keywords)


def get_min_start_date(leave_type: str, today: date, token: str = "") -> date:
    """Calculate the earliest allowable start date based on company policy, ensuring required business days notice."""
    if leave_type != "annual":
        return today

    lead_days = get_annual_leave_lead_days_from_policy(token)
    candidate = today + timedelta(days=1)
    while True:
        lead_time_days = sum(
            (today + timedelta(days=offset)).weekday() < 5
            for offset in range(1, (candidate - today).days)
        )
        if lead_time_days >= lead_days and candidate.weekday() < 5:
            return candidate
        candidate += timedelta(days=1)
