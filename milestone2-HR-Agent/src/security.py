"""Security helpers. Complete every TODO before persisting telemetry."""
from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from typing import Any


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


def connect_db(
    database_url: str,
    *,
    row_factory: Any = None,
    connector: Any = None,
) -> Any:
    """Connect to PostgreSQL, retrying localhost if Docker host `postgres` is unreachable."""
    if connector is None:
        import psycopg

        connector = psycopg.connect
    kwargs = {"row_factory": row_factory} if row_factory is not None else {}
    try:
        return connector(database_url, **kwargs)
    except Exception:
        if "@postgres:" in database_url:
            return connector(database_url.replace("@postgres:", "@localhost:"), **kwargs)
        raise


def _load_medical_terms() -> tuple[str, ...]:
    """Load reviewable medical terms from database table medical_terms as single source of truth."""
    global _CACHED_TERMS
    if _CACHED_TERMS is not None:
        return _CACHED_TERMS

    try:
        from .config import get_settings

        settings = get_settings()
        if settings.database_url:
            with connect_db(settings.database_url) as conn:
                rows = conn.execute(
                    "SELECT term FROM medical_terms ORDER BY LENGTH(term) DESC"
                ).fetchall()
                if rows:
                    terms = tuple(
                        term
                        for term in (
                            (r[0] if isinstance(r, (tuple, list)) else r["term"]).strip()
                            for r in rows
                        )
                        if term
                    )
                    if terms:
                        _CACHED_TERMS = terms
                        return _CACHED_TERMS
    except Exception:
        pass

    return ()


def _build_medical_term_re(terms: tuple[str, ...] | None = None) -> re.Pattern:
    active_terms = _load_medical_terms() if terms is None else terms
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
    if active_terms:
        # Sort descending by length so longer compound terms precede shorter substrings
        sorted_terms = sorted(active_terms, key=len, reverse=True)
        pattern_terms = "|".join(re.escape(term) for term in sorted_terms)
        pattern = rf"\b(?:{pattern_terms})\b|{hr_lookbehinds}\bsakit\b{hr_suffix_lookahead}"
    else:
        pattern = rf"{hr_lookbehinds}\bsakit\b{hr_suffix_lookahead}"
    return re.compile(pattern, re.IGNORECASE)


_MEDICAL_TERM_RE = _build_medical_term_re()


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def stable_safety_id(employee_id: str) -> str:
    return token_hash(employee_id)


def redact(value: str) -> str:
    global _MEDICAL_TERM_RE
    if _CACHED_TERMS is None:
        _MEDICAL_TERM_RE = _build_medical_term_re()
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

