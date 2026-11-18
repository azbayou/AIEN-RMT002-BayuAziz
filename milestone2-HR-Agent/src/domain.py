from __future__ import annotations
import re
from datetime import date, timedelta
from typing import Any
from .contracts import LeaveBalance, PrepareLeaveArgs

class DomainError(ValueError):
    pass


INDONESIAN_NUMBERS: dict[str, int] = {
    "nol": 0,
    "tanpa": 0,
    "satu": 1,
    "sehari": 1,
    "dua": 2,
    "tiga": 3,
    "empat": 4,
    "lima": 5,
    "enam": 6,
    "tujuh": 7,
    "delapan": 8,
    "sembilan": 9,
    "sepuluh": 10,
    "sebelas": 11,
    "dua belas": 12,
    "tiga belas": 13,
    "empat belas": 14,
    "lima belas": 15,
    "enam belas": 16,
    "tujuh belas": 17,
    "delapan belas": 18,
    "sembilan belas": 19,
    "dua puluh": 20,
    "dua puluh satu": 21,
    "dua puluh dua": 22,
    "dua puluh tiga": 23,
    "dua puluh empat": 24,
    "dua puluh lima": 25,
    "dua puluh enam": 26,
    "dua puluh tujuh": 27,
    "dua puluh delapan": 28,
    "dua puluh sembilan": 29,
    "tiga puluh": 30,
}

_NUMBER_ALIASES = {"tanpa", "sehari"}
NUMBER_TO_INDONESIAN: dict[int, str] = {
    v: k for k, v in INDONESIAN_NUMBERS.items() if k not in _NUMBER_ALIASES
}

_INDONESIAN_WORD_ALTERNATION = "|".join(
    r"\s+".join(re.escape(part) for part in word.split())
    for word in sorted(INDONESIAN_NUMBERS, key=len, reverse=True)
)
_POLICY_NUMBER_CAPTURE = rf"([0-9]+|\b(?:{_INDONESIAN_WORD_ALTERNATION})\b)"


def _parse_policy_number(raw: str) -> int | None:
    """Parse numeric string (0..365) or Indonesian number word (0..30)."""
    cleaned = " ".join(raw.strip().casefold().split())
    if not cleaned:
        return None
    if cleaned.isdigit():
        value = int(cleaned)
        return value if 0 <= value <= 365 else None
    return INDONESIAN_NUMBERS.get(cleaned)


def get_annual_leave_lead_days(policy_text: str | None = None) -> int:
    """Ekstrak dinamis angka batas pengajuan minimal cuti tahunan (lead time hari kerja).

    Membaca ketentuan dari teks kebijakan database (policy_chunks) atau hasil pencarian RAG.
    Mencari pola batas waktu pengajuan seperti 'paling lambat <angka/kata> hari kerja',
    'minimal <angka/kata> hari kerja', 'sekurang-kurangnya <angka/kata> hari kerja',
    '<angka/kata> hari kerja sebelum', 'sehari kerja sebelum', 'tanpa batas', atau 'H-N'.
    Jika kebijakan di database berubah, batas lead time otomatis menyesuaikan tanpa hardcode.
    Default fallback: 3 hari kerja.
    """
    if policy_text:
        patterns = (
            rf"(?:paling\s+lambat|minimal|paling\s+sedikit|sekurang[- ]kurangnya)\s+{_POLICY_NUMBER_CAPTURE}\s+hari\s+kerja",
            rf"{_POLICY_NUMBER_CAPTURE}\s+hari\s+kerja\s+sebelum",
            r"\bH\s*-\s*([0-9]+)\b",
        )
        for pattern in patterns:
            match = re.search(pattern, policy_text, re.IGNORECASE)
            if match:
                parsed = _parse_policy_number(match.group(1))
                if parsed is not None:
                    return parsed
        if re.search(r"\bsehari\s+kerja\s+sebelum\b", policy_text, re.IGNORECASE):
            return 1
        if re.search(r"\btanpa\s+batas\b", policy_text, re.IGNORECASE):
            return 0

    return 3


def get_sick_leave_doc_threshold(policy_text: str | None = None) -> int:
    """Ekstrak dinamis ambang batas cuti sakit berturut-turut yang mewajibkan dokumen pendukung.

    Membaca ketentuan dari teks kebijakan database (policy_chunks) atau hasil pencarian RAG.
    Mencari pola 'lebih dari <angka/kata> hari kerja', '> <angka> hari kerja',
    atau 'minimal <angka/kata> hari kerja'.
    Jika kebijakan di database berubah, ambang batas otomatis menyesuaikan tanpa hardcode.
    Default fallback: 2 hari kerja.
    """
    if policy_text:
        for pattern in (
            rf"lebih\s+dari\s+{_POLICY_NUMBER_CAPTURE}\s+hari\s+kerja",
            r">\s*([0-9]+)\s*hari\s+kerja",
        ):
            match = re.search(pattern, policy_text, re.IGNORECASE)
            if match:
                parsed = _parse_policy_number(match.group(1))
                if parsed is not None:
                    return parsed
        min_match = re.search(
            rf"minimal\s+{_POLICY_NUMBER_CAPTURE}\s+hari\s+kerja",
            policy_text,
            re.IGNORECASE,
        )
        if min_match:
            parsed = _parse_policy_number(min_match.group(1))
            if parsed is not None:
                return max(0, parsed - 1)

    return 2


def count_lead_business_days(today: date, start_date: date) -> int:
    """Count business days ahead from today (exclusive of today, inclusive of start_date)."""
    if start_date <= today:
        return 0
    return sum(
        (today + timedelta(days=offset)).weekday() < 5
        for offset in range(1, (start_date - today).days + 1)
    )


def compute_earliest_annual_leave_date(today: date, lead_days: int) -> date:
    """Return earliest weekday satisfying annual leave lead-time days from today."""
    candidate = today if lead_days <= 0 else today + timedelta(days=1)
    while True:
        if candidate.weekday() < 5 and (
            lead_days <= 0 or count_lead_business_days(today, candidate) >= lead_days
        ):
            return candidate
        candidate += timedelta(days=1)


def business_days(start: date, end: date) -> int:
    if start > end:
        raise DomainError(
            "tanggal selesai tidak boleh sebelum tanggal mulai; "
            "mohon perbaiki urutan tanggal yang terbalik (sistem tidak menukar tanggal otomatis dan tidak membuat proposal)"
        )
    if (end - start).days > 366:
        raise DomainError("rentang tanggal cuti melebihi batas maksimum satu tahun")

    days = sum(
        (start + timedelta(days=offset)).weekday() < 5
        for offset in range((end - start).days + 1)
    )
    if days == 0:
        raise DomainError(
            "rentang tanggal harus memiliki hari kerja "
            "(akhir pekan Sabtu–Minggu berisi 0 hari kerja; proposal ditolak dan saldo cuti tidak dipotong)"
        )
    return days


def validate_leave_request(
    args: PrepareLeaveArgs,
    balances: list[LeaveBalance],
    overlaps: bool,
    today: date,
    policy_text: str | None = None,
    pending_days: int = 0,
    pending_requests: list[Any] | None = None,
) -> tuple[int, list[str]]:
    if args.start_date < today or args.end_date < today:
        raise DomainError("tanggal cuti tidak boleh masa lalu")
    if args.start_date > args.end_date:
        raise DomainError(
            "tanggal selesai tidak boleh sebelum tanggal mulai; "
            "mohon perbaiki urutan tanggal yang terbalik (sistem tidak menukar tanggal otomatis dan tidak membuat proposal)"
        )

    days = business_days(args.start_date, args.end_date)

    if args.leave_type == "annual":
        lead_days = get_annual_leave_lead_days(policy_text)
        if count_lead_business_days(today, args.start_date) < lead_days:
            days_word = NUMBER_TO_INDONESIAN.get(lead_days, str(lead_days))
            raise DomainError(f"cuti tahunan harus diajukan minimal {days_word} hari kerja sebelumnya")

    if overlaps:
        raise DomainError("tanggal cuti bertumpang tindih dengan permintaan aktif")

    balance = next(
        (item for item in balances if item.leave_type == args.leave_type),
        None,
    )
    reserved = pending_days
    if pending_requests:
        reserved += sum(
            getattr(r, "business_days", 0)
            for r in pending_requests
            if getattr(r, "status", None) == "pending_manager_review"
            and getattr(r, "leave_type", None) == args.leave_type
        )
    effective_days = (balance.available_days - reserved) if balance is not None else 0
    if balance is None or effective_days < days:
        raise DomainError(
            f"saldo cuti tidak cukup (diminta {days} hari kerja, saldo tersedia hanya {effective_days} hari kerja; "
            "persetujuan lisan tidak membolehkan saldo minus dan proposal ditolak)"
        )

    summary = [f"Saldo {args.leave_type} mencukupi untuk {days} hari kerja"]
    if args.leave_type == "sick":
        threshold = get_sick_leave_doc_threshold(policy_text)
        if days > threshold:
            summary.append(f"Wajib melampirkan bukti foto surat dokter (cuti sakit > {threshold} hari kerja)")
        else:
            summary.append(f"Surat dokter opsional (cuti sakit <= {threshold} hari kerja)")
    return days, summary


def estimate_cost(
    input_tokens: int,
    output_tokens: int,
    input_rate: float | None,
    output_rate: float | None,
) -> float | None:
    if input_rate is None or output_rate is None:
        return None
    return (input_tokens * input_rate + output_tokens * output_rate) / 1_000_000
