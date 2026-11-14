"""Security helpers. Complete every TODO before persisting telemetry."""
from __future__ import annotations

import hashlib
import hmac
import json
from pathlib import Path
import re
import secrets


_EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
_PHONE_RE = re.compile(r"(?<!\w)(?:\+?62[\s.-]?|0)8[1-9](?:[\s.-]?\d){7,11}(?!\w)")
_TOKEN_RE = re.compile(
    r"(?<![\w-])(?:bearer\s+)?(?:token[-_][A-Z0-9._-]+|sk-[A-Z0-9._-]{8,}|"
    r"secret[-_][A-Z0-9._-]+|api[-_]?key[-_][A-Z0-9._-]+)(?![\w-])",
    re.IGNORECASE,
)
_MEDICAL_LABEL_RE = re.compile(
    r"(?i)\b(?:diagnosis|diagnosa|medical(?:\s+detail)?|medis|penyakit|"
    r"kondisi\s+kesehatan)\s*:\s*[^.;,\n]+"
)

_CACHED_TERMS: tuple[str, ...] | None = None


def _load_medical_terms() -> tuple[str, ...]:
    """Load reviewable medical terms from database table medical_terms as single source of truth."""
    global _CACHED_TERMS
    if _CACHED_TERMS is not None:
        return _CACHED_TERMS

    # 1. Load from NeonDB
    try:
        from .config import get_settings
        import psycopg
        settings = get_settings()
        if settings.database_url:
            with psycopg.connect(settings.database_url) as conn:
                rows = conn.execute("SELECT term FROM medical_terms ORDER BY LENGTH(term) DESC").fetchall()
                if rows:
                    _CACHED_TERMS = tuple(r[0] if isinstance(r, (tuple, list)) else r["term"] for r in rows)
                    return _CACHED_TERMS
    except Exception:
        pass

    # 2. Fallback for offline tests when database is not connected
    _FALLBACK_TERMS = (
        "covid-19", "diabetes", "hipertensi", "asma", "kanker", "depresi",
        "covid", "migrain", "cedera", "stroke", "jantung", "kolesterol",
        "alergi", "hepatitis", "demam", "flu"
    )
    _CACHED_TERMS = _FALLBACK_TERMS
    return _CACHED_TERMS


def _build_medical_term_re(terms: tuple[str, ...] | None = None) -> re.Pattern:
    active_terms = terms or _load_medical_terms()
    # Sort descending by length so longer patterns like 'covid-19' precede 'covid'
    sorted_terms = sorted(active_terms, key=len, reverse=True)
    pattern_terms = "|".join(re.escape(term) for term in sorted_terms)
    hr_lookbehinds = (
        r"(?<!cuti\s)"
        r"(?<!izin\s)"
        r"(?<!tipe\s)"
        r"(?<!saldo\s)"
        r"(?<!jatah\s)"
        r"(?<!jenis\s)"
        r"(?<!hak\s)"
        r"(?<!kategori\s)"
    )
    hr_suffix_lookahead = r"(?!\s*:\s*\d+\s*(?:hari(?:\s*kerja)?))"
    return re.compile(
        rf"\b(?:{pattern_terms})\b|{hr_lookbehinds}\bsakit\b{hr_suffix_lookahead}",
        re.IGNORECASE,
    )


_MEDICAL_TERM_RE = _build_medical_term_re()


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def stable_safety_id(employee_id: str) -> str:
    return token_hash(employee_id)


def redact(value: str) -> str:
    redacted = _EMAIL_RE.sub("[REDACTED_EMAIL]", value)
    redacted = _PHONE_RE.sub("[REDACTED_PHONE]", redacted)
    redacted = _TOKEN_RE.sub("[REDACTED_TOKEN]", redacted)
    redacted = _MEDICAL_LABEL_RE.sub("[REDACTED_MEDICAL]", redacted)
    return _MEDICAL_TERM_RE.sub("[REDACTED_MEDICAL]", redacted)


def hash_password(password: str, salt: str | None = None) -> str:
    """Hash password with PBKDF2-HMAC-SHA256 and random/provided salt."""
    active_salt = salt or secrets.token_hex(16)
    derived = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        active_salt.encode("utf-8"),
        100_000,
    ).hex()
    return f"pbkdf2_sha256${active_salt}${derived}"


def verify_password(password: str, stored_hash: str) -> bool:
    """Constant-time verification of a password against a stored PBKDF2 hash."""
    if not stored_hash or "$" not in stored_hash:
        return False
    parts = stored_hash.split("$")
    if len(parts) != 3 or parts[0] != "pbkdf2_sha256":
        return False
    _, salt, _ = parts
    candidate = hash_password(password, salt=salt)
    return hmac.compare_digest(candidate, stored_hash)

