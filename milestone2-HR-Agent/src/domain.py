from __future__ import annotations
import re
from datetime import date, timedelta
from pathlib import Path
from typing import Any
from .contracts import LeaveBalance, PrepareLeaveArgs

class DomainError(ValueError):
    pass


INDONESIAN_NUMBERS: dict[str, int] = {
    "satu": 1,
    "dua": 2,
    "tiga": 3,
    "empat": 4,
    "lima": 5,
    "enam": 6,
    "tujuh": 7,
    "delapan": 8,
    "sembilan": 9,
    "sepuluh": 10,
}

NUMBER_TO_INDONESIAN: dict[int, str] = {v: k for k, v in INDONESIAN_NUMBERS.items()}


def get_annual_leave_lead_days(policy_text: str | None = None) -> int:
    """Ekstrak dinamis angka batas pengajuan minimal cuti tahunan (lead time hari kerja).

    Membaca ketentuan dari dokumen kebijakan (misalnya data/policies/annual-leave.md atau teks RAG).
    Mencari pola batas waktu pengajuan seperti 'paling lambat <angka/kata> hari kerja' atau 'minimal <angka/kata> hari kerja'.
    Jika kebijakan berubah, batas lead time otomatis menyesuaikan tanpa hardcode.
    Default fallback: 3 hari kerja.
    """
    if policy_text is None:
        policy_path = Path(__file__).resolve().parent.parent / "data" / "policies" / "annual-leave.md"
        if policy_path.exists():
            try:
                policy_text = policy_path.read_text(encoding="utf-8")
            except Exception:
                policy_text = ""

    if policy_text:
        match = re.search(
            r"(?:paling\s+lambat|minimal|paling\s+sedikit|sekurang[- ]kurangnya)\s+([a-zA-Z0-9]+)\s+hari\s+kerja",
            policy_text,
            re.IGNORECASE,
        )
        if not match:
            match = re.search(
                r"([a-zA-Z0-9]+)\s+hari\s+kerja\s+sebelum",
                policy_text,
                re.IGNORECASE,
            )
        if not match:
            match = re.search(
                r"\bH-?([0-9]+)\b",
                policy_text,
                re.IGNORECASE,
            )
        if match:
            raw = match.group(1).lower()
            if raw.isdigit():
                return int(raw)
            if raw in INDONESIAN_NUMBERS:
                return INDONESIAN_NUMBERS[raw]

    return 3


def get_sick_leave_doc_threshold(policy_text: str | None = None) -> int:
    """Ekstrak dinamis ambang batas cuti sakit berturut-turut yang mewajibkan dokumen pendukung.

    Membaca ketentuan dari dokumen kebijakan (misalnya data/policies/sick-leave.md atau teks RAG).
    Mencari pola 'lebih dari <angka/kata> hari kerja'.
    Jika kebijakan berubah, ambang batas otomatis menyesuaikan tanpa hardcode.
    Default fallback: 2 hari kerja.
    """
    if policy_text is None:
        policy_path = Path(__file__).resolve().parent.parent / "data" / "policies" / "sick-leave.md"
        if policy_path.exists():
            try:
                policy_text = policy_path.read_text(encoding="utf-8")
            except Exception:
                policy_text = ""

    if policy_text:
        match = re.search(
            r"lebih\s+dari\s+([a-zA-Z0-9]+)\s+hari\s+kerja",
            policy_text,
            re.IGNORECASE,
        )
        if match:
            raw = match.group(1).lower()
            if raw.isdigit():
                return int(raw)
            if raw in INDONESIAN_NUMBERS:
                return INDONESIAN_NUMBERS[raw]

    return 2


def business_days(start: date, end: date) -> int:
    if start > end:
        raise DomainError("tanggal mulai tidak boleh sebelum tanggal selesai")
    if (end - start).days > 366:
        raise DomainError("rentang tanggal cuti melebihi batas maksimum satu tahun")

    days = sum(
        (start + timedelta(days=offset)).weekday() < 5
        for offset in range((end - start).days + 1)
    )
    if days == 0:
        raise DomainError("rentang tanggal harus memiliki hari kerja")
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
        raise DomainError("tanggal mulai tidak boleh sebelum tanggal selesai")

    days = business_days(args.start_date, args.end_date)

    if args.leave_type == "annual":
        lead_days = get_annual_leave_lead_days(policy_text)
        lead_time_days = sum(
            (today + timedelta(days=offset)).weekday() < 5
            for offset in range(1, (args.start_date - today).days)
        )
        if lead_time_days < lead_days:
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
        raise DomainError("saldo cuti tidak cukup")

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
