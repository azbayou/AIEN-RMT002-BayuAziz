"""Dynamic policy retrieval and rule parsing via backend policy_rules API and RAG."""
from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any

import httpx
import streamlit as st

from ui.config import API_URL
from ui_contract import API_PATHS

_DEFAULT_ANNUAL_LEAD_DAYS = 3
_DEFAULT_SICK_DOC_THRESHOLD = 2
_DEFAULT_ANNUAL_ENTITLEMENT_DAYS = 12


def _resolve_token(token: str = "") -> str:
    if token:
        return token
    try:
        active_persona = st.session_state.get("active_persona") or {}
        return active_persona.get("demo_token", "") or ""
    except Exception:
        return ""


def _default_parental_leave_summary(rule_summary: str = "") -> dict[str, str]:
    """Return in-memory parental leave policy summary backed by policy_rules API."""
    return {
        "eligibility": "Berlaku bagi pegawai tetap dengan masa kerja minimal 6 bulan.",
        "process": rule_summary
        or "Permohonan akan diverifikasi lebih lanjut oleh tim HR (asisten menyiapkan permintaan dan membuat tiket konsultasi).",
        "tenure": "minimal 6 bulan",
        "verification": "Keputusan kelayakan dan durasi akhir dilakukan manusia dari tim HR",
        "summary": rule_summary
        or "Berdasarkan kebijakan [HR-LEAVE-003], cuti orang tua mengikuti hak cuti melahirkan / hak ayah sesuai undang-undang dan kebijakan perusahaan.",
        "source": "policy_rules_api",
    }


@st.cache_data(ttl=120, show_spinner=False)
def _fetch_policy_rules_cached(api_url: str) -> dict[str, Any]:
    """Fetch structured policy rules from GET /api/v1/policies/rules (cached 120s)."""
    resp = httpx.get(f"{api_url.rstrip('/')}{API_PATHS['policy_rules']}", timeout=5.0)
    resp.raise_for_status()
    data = resp.json()
    if not isinstance(data, dict):
        raise ValueError("Invalid policy rules response payload.")
    return data


def _fetch_policy_rules(api_url: str = API_URL) -> dict[str, Any]:
    """Fetch structured policy rules safely without caching transient network failures."""
    try:
        return _fetch_policy_rules_cached(api_url)
    except Exception:
        return {}


def _post_chat_query(api_url: str, token: str, message: str) -> str:
    """Query backend RAG chat endpoint and return answer text."""
    for chat_path in (API_PATHS["chat"], "/chat"):
        try:
            resp = httpx.post(
                f"{api_url.rstrip('/')}{chat_path}",
                headers={"Authorization": f"Bearer {token}"},
                json={"message": message},
                timeout=20.0,
            )
            if resp.status_code == 200:
                answer = resp.json().get("answer", "").strip()
                if answer:
                    return answer
        except Exception:
            continue
    return ""


@st.cache_data(ttl=120, show_spinner=False)
def _query_agent_for_lead_days(api_url: str, token: str) -> int:
    """Menanyakan langsung ke AI Agent melalui endpoint /chat untuk menganalisis kebijakan resmi via RAG."""
    query_msg = (
        "Berapa hari minimal pengajuan cuti tahunan sebelum tanggal mulai menurut kebijakan HR? "
        "Sebutkan angka harinya secara jelas."
    )
    answer = _post_chat_query(api_url, token, query_msg).lower()
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

    return _DEFAULT_ANNUAL_LEAD_DAYS


def get_annual_leave_lead_days_from_policy(token: str = "") -> int:
    """Mengambil batas minimal hari pengajuan cuti tahunan (H-x) dari /api/v1/policies/rules atau RAG."""
    rules = _fetch_policy_rules(API_URL)
    lead_days = rules.get("annual_lead_days")
    if isinstance(lead_days, int) and lead_days >= 0:
        return lead_days

    resolved_token = _resolve_token(token)
    if resolved_token:
        return _query_agent_for_lead_days(API_URL, resolved_token)

    return _DEFAULT_ANNUAL_LEAD_DAYS


@st.cache_data(ttl=120, show_spinner=False)
def get_parental_leave_policy_summary(token: str = "") -> dict[str, str]:
    """Mendapatkan ringkasan kebijakan cuti orang tua [HR-LEAVE-003] via policy_rules API / RAG."""
    rules = _fetch_policy_rules(API_URL)
    parental_rule = (rules.get("policy_summaries") or {}).get("parental") or {}
    rule_summary = str(parental_rule.get("summary") or "").strip()
    fallback_data = _default_parental_leave_summary(rule_summary)

    resolved_token = _resolve_token(token)
    if not resolved_token:
        return fallback_data

    query_msg = (
        "Menurut kebijakan cuti orang tua [HR-LEAVE-003], apa syarat kelayakan masa kerja pegawai "
        "dan bagaimana proses verifikasi atau pengajuannya? Sebutkan secara ringkas."
    )
    answer = _post_chat_query(API_URL, resolved_token, query_msg)
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

        return {
            "eligibility": eligibility or fallback_data["eligibility"],
            "process": process or fallback_data["process"],
            "tenure": "minimal 6 bulan",
            "verification": "Keputusan kelayakan dan durasi akhir dilakukan manusia dari tim HR",
            "summary": answer,
            "source": "rag_agent",
        }

    return fallback_data


@st.cache_data(ttl=120, show_spinner=False)
def get_annual_leave_entitlement_from_policy(token: str = "") -> int:
    """Mengambil jatah cuti tahunan resmi perusahaan dari kebijakan [HR-LEAVE-001] via API / RAG."""
    rules = _fetch_policy_rules(API_URL)
    entitlement = rules.get("annual_entitlement_days")
    if isinstance(entitlement, int) and 1 <= entitlement <= 365:
        return entitlement

    resolved_token = _resolve_token(token)
    if not resolved_token:
        return _DEFAULT_ANNUAL_ENTITLEMENT_DAYS

    query_msg = (
        "Menurut kebijakan cuti tahunan [HR-LEAVE-001], berapa hari kerja jatah cuti tahunan "
        "per tahun kalender bagi pegawai tetap? Sebutkan angka harinya secara jelas."
    )
    answer = _post_chat_query(API_URL, resolved_token, query_msg).lower()
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

    return _DEFAULT_ANNUAL_ENTITLEMENT_DAYS


@st.cache_data(ttl=120, show_spinner=False)
def _query_agent_for_sick_threshold(api_url: str, token: str) -> int:
    """Menanyakan langsung ke AI Agent melalui endpoint /chat untuk menganalisis kebijakan cuti sakit via RAG."""
    query_msg = (
        "Menurut kebijakan cuti sakit [HR-LEAVE-002], berapa batas maksimal hari kerja berturut-turut tanpa memerlukan surat dokter? "
        "Sebutkan angka harinya secara jelas."
    )
    answer = _post_chat_query(api_url, token, query_msg).lower()
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

    return _DEFAULT_SICK_DOC_THRESHOLD


def get_sick_leave_doc_threshold_from_policy(token: str = "") -> int:
    """Mengambil batas hari cuti sakit tanpa surat dokter dari /api/v1/policies/rules atau RAG."""
    rules = _fetch_policy_rules(API_URL)
    sick_thresh = rules.get("sick_doc_threshold")
    if isinstance(sick_thresh, int) and sick_thresh >= 0:
        return sick_thresh

    resolved_token = _resolve_token(token)
    if resolved_token:
        return _query_agent_for_sick_threshold(API_URL, resolved_token)

    return _DEFAULT_SICK_DOC_THRESHOLD


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
