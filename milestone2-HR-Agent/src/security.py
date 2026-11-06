"""Security helpers. Complete every TODO before persisting telemetry."""
from __future__ import annotations

import hashlib
import re


_EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
_PHONE_RE = re.compile(r"(?<!\w)(?:\+62|62|0)8[1-9](?:[\s.-]?\d){7,11}(?!\w)")
_TOKEN_RE = re.compile(
    r"(?<![\w-])(?:bearer\s+)?(?:token[-_][A-Z0-9._-]+|sk-[A-Z0-9._-]{8,}|"
    r"secret[-_][A-Z0-9._-]+|api[-_]?key[-_][A-Z0-9._-]+)(?![\w-])",
    re.IGNORECASE,
)
_MEDICAL_LABEL_RE = re.compile(
    r"(?i)\b(?:diagnosis|diagnosa|medical(?:\s+detail)?|medis|penyakit|"
    r"kondisi\s+kesehatan)\s*:\s*[^.;,\n]+"
)
_MEDICAL_TERM_RE = re.compile(
    r"(?i)\b(?:diabetes|hipertensi|asma|kanker|depresi|covid(?:-19)?|"
    r"flu|demam|migrain|cedera|sakit)\b"
)


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
