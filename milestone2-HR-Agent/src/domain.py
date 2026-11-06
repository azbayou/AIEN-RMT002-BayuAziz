from __future__ import annotations
from datetime import date, timedelta
from .contracts import LeaveBalance, PrepareLeaveArgs

class DomainError(ValueError):
    pass


def business_days(start: date, end: date) -> int:
    if start > end:
        raise DomainError("tanggal mulai tidak boleh sebelum tanggal selesai")

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
) -> tuple[int, list[str]]:
    if args.start_date < today or args.end_date < today:
        raise DomainError("tanggal cuti tidak boleh masa lalu")
    if args.start_date > args.end_date:
        raise DomainError("tanggal mulai tidak boleh sebelum tanggal selesai")

    days = business_days(args.start_date, args.end_date)

    if args.leave_type == "annual":
        lead_time_days = sum(
            (today + timedelta(days=offset)).weekday() < 5
            for offset in range(1, (args.start_date - today).days)
        )
        if lead_time_days < 3:
            raise DomainError("cuti tahunan harus diajukan minimal tiga hari kerja sebelumnya")

    if overlaps:
        raise DomainError("tanggal cuti bertumpang tindih dengan permintaan aktif")

    balance = next(
        (item for item in balances if item.leave_type == args.leave_type),
        None,
    )
    if balance is None or balance.available_days < days:
        raise DomainError("saldo cuti tidak cukup")

    return days, [f"Saldo {args.leave_type} mencukupi untuk {days} hari kerja"]


def estimate_cost(
    input_tokens: int,
    output_tokens: int,
    input_rate: float | None,
    output_rate: float | None,
) -> float | None:
    if input_rate is None or output_rate is None:
        return None
    return (input_tokens * input_rate + output_tokens * output_rate) / 1_000_000
