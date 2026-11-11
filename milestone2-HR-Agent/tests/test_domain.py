from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError

from src.contracts import LeaveBalance, PrepareLeaveArgs
from src.domain import (
    DomainError,
    business_days,
    get_annual_leave_lead_days,
    validate_leave_request,
)


def test_business_days_excludes_weekend() -> None:
    assert business_days(date(2026, 9, 25), date(2026, 9, 28)) == 2


def test_weekend_only_range_is_blocked() -> None:
    with pytest.raises(DomainError, match="hari kerja"):
        business_days(date(2026, 9, 26), date(2026, 9, 27))


def test_business_day_boundaries_are_inclusive() -> None:
    assert business_days(date(2026, 9, 28), date(2026, 9, 28)) == 1


@pytest.mark.parametrize(
    "start,end,message",
    [
        (date(2026, 9, 22), date(2026, 9, 24), "masa lalu"),
        (date(2026, 9, 25), date(2026, 9, 24), "sebelum"),
    ],
)
def test_invalid_dates_are_blocked(start: date, end: date, message: str) -> None:
    args = PrepareLeaveArgs(start_date=start, end_date=end, leave_type="annual", reason=None)
    with pytest.raises(DomainError, match=message):
        validate_leave_request(
            args,
            [LeaveBalance(leave_type="annual", available_days=8, as_of_date=date(2026, 1, 1))],
            False,
            date(2026, 9, 23),
        )


def test_insufficient_balance_and_overlap_are_blocked() -> None:
    args = PrepareLeaveArgs(
        start_date=date(2026, 10, 1), end_date=date(2026, 10, 9), leave_type="annual", reason=None
    )
    balance = [LeaveBalance(leave_type="annual", available_days=2, as_of_date=date(2026, 1, 1))]
    with pytest.raises(DomainError, match="tidak cukup"):
        validate_leave_request(args, balance, False, date(2026, 9, 23))
    with pytest.raises(DomainError, match="bertumpang tindih"):
        validate_leave_request(args, balance, True, date(2026, 9, 23))


def test_unsupported_leave_type_is_rejected_by_contract() -> None:
    with pytest.raises(ValidationError):
        PrepareLeaveArgs(
            start_date=date(2026, 10, 1),
            end_date=date(2026, 10, 2),
            leave_type="study",
            reason=None,
        )


def test_annual_leave_requires_three_business_days_lead_time() -> None:
    balance = [LeaveBalance(leave_type="annual", available_days=8, as_of_date=date(2026, 1, 1))]
    args = PrepareLeaveArgs(
        start_date=date(2026, 9, 28), end_date=date(2026, 9, 28), leave_type="annual", reason=None
    )
    with pytest.raises(DomainError, match="tiga hari kerja"):
        validate_leave_request(args, balance, False, date(2026, 9, 23))

    valid = args.model_copy(update={"start_date": date(2026, 9, 29), "end_date": date(2026, 9, 29)})
    days, _ = validate_leave_request(valid, balance, False, date(2026, 9, 23))
    assert days == 1


def test_dynamic_annual_leave_lead_days() -> None:
    # 1. Fallback from policy file or default (default is 3)
    assert get_annual_leave_lead_days() == 3

    # 2. Dynamic policy extraction
    assert get_annual_leave_lead_days("Pengajuan dilakukan paling lambat dua hari kerja sebelum tanggal mulai") == 2
    assert get_annual_leave_lead_days("Pengajuan minimal 4 hari kerja sebelumnya") == 4
    assert get_annual_leave_lead_days("Pengajuan dilakukan minimal satu hari kerja sebelumnya") == 1
    assert get_annual_leave_lead_days("Pengajuan minimal H-5 sebelum cuti") == 5
    assert get_annual_leave_lead_days("Kebijakan tanpa klausul batas hari") == 3

    # 3. Dynamic validation threshold
    balance = [LeaveBalance(leave_type="annual", available_days=8, as_of_date=date(2026, 1, 1))]
    # today: Wednesday 2026-09-23, start: Friday 2026-09-25 -> 1 business day lead time (Thursday 2026-09-24)
    args_1d = PrepareLeaveArgs(
        start_date=date(2026, 9, 25), end_date=date(2026, 9, 25), leave_type="annual", reason=None
    )
    # Default requires 3 days -> fails
    with pytest.raises(DomainError, match="tiga hari kerja"):
        validate_leave_request(args_1d, balance, False, date(2026, 9, 23))

    # With policy specifying 1 day lead time -> passes
    policy_1d = "Pengajuan dilakukan paling lambat satu hari kerja sebelum tanggal mulai."
    days, _ = validate_leave_request(args_1d, balance, False, date(2026, 9, 23), policy_text=policy_1d)
    assert days == 1

    # With policy specifying 2 days lead time -> fails with dynamic message "dua hari kerja"
    policy_2d = "Pengajuan dilakukan paling lambat dua hari kerja sebelum tanggal mulai."
    with pytest.raises(DomainError, match="dua hari kerja"):
        validate_leave_request(args_1d, balance, False, date(2026, 9, 23), policy_text=policy_2d)


def test_validate_leave_request_reserves_pending_balance() -> None:
    balance = [LeaveBalance(leave_type="annual", available_days=8, as_of_date=date(2026, 1, 1))]
    args = PrepareLeaveArgs(
        start_date=date(2026, 10, 5), end_date=date(2026, 10, 9), leave_type="annual", reason=None
    )  # 5 business days
    # With 0 pending days: 8 available >= 5 -> passes
    days, _ = validate_leave_request(args, balance, False, date(2026, 9, 23), pending_days=0)
    assert days == 5

    # With 4 pending days: effective = 8 - 4 = 4 < 5 -> raises DomainError
    with pytest.raises(DomainError, match="saldo cuti tidak cukup"):
        validate_leave_request(args, balance, False, date(2026, 9, 23), pending_days=4)


