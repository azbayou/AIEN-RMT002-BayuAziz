from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor

import pytest

from src.contracts import ActionProposal, PrepareLeaveArgs
from src.domain import DomainError, validate_leave_request
from src.repository import ConflictError, MemoryRepository


def proposal() -> ActionProposal:
    return ActionProposal(
        proposal_id="AP-TEST",
        leave_type="annual",
        start_date=date(2026, 11, 2),
        end_date=date(2026, 11, 3),
        business_days=2,
        validation_summary=["valid"],
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
    )


def test_confirmation_is_pending_only_and_idempotent(repository: MemoryRepository) -> None:
    repository.save_proposal("EMP-001", proposal())
    assert repository.list_leave_requests("EMP-001") == []
    first = repository.confirm_proposal("EMP-001", "AP-TEST", "idem-12345678")
    replay = repository.confirm_proposal("EMP-001", "AP-TEST", "idem-12345678")
    assert first.status == "pending_manager_review"
    assert replay.request_id == first.request_id
    assert replay.idempotent_replay is True
    assert repository.list_leave_requests("EMP-001")[0].status == "pending_manager_review"


def test_confirmation_rejects_wrong_identity_and_key(repository: MemoryRepository) -> None:
    repository.save_proposal("EMP-001", proposal())
    with pytest.raises(KeyError):
        repository.confirm_proposal("EMP-002", "AP-TEST", "idem-12345678")
    repository.confirm_proposal("EMP-001", "AP-TEST", "idem-12345678")
    with pytest.raises(ConflictError):
        repository.confirm_proposal("EMP-001", "AP-TEST", "another-key")


def test_expired_proposal_is_rejected(repository: MemoryRepository) -> None:
    item = proposal().model_copy(update={"expires_at": datetime.now(timezone.utc) - timedelta(seconds=1)})
    repository.save_proposal("EMP-001", item)
    with pytest.raises(ConflictError, match="expired"):
        repository.confirm_proposal("EMP-001", "AP-TEST", "idem-12345678")


def test_overlap_is_rejected_before_a_second_request_is_saved(repository: MemoryRepository) -> None:
    repository.save_proposal("EMP-001", proposal())
    repository.confirm_proposal("EMP-001", "AP-TEST", "idem-12345678")

    assert repository.has_overlap("EMP-001", date(2026, 11, 3), date(2026, 11, 4))
    with pytest.raises(DomainError, match="bertumpang tindih"):
        validate_leave_request(
            PrepareLeaveArgs(
                start_date=date(2026, 11, 3),
                end_date=date(2026, 11, 4),
                leave_type="annual",
            ),
            repository.get_balances("EMP-001"),
            repository.has_overlap("EMP-001", date(2026, 11, 3), date(2026, 11, 4)),
            date(2026, 10, 1),
        )
    assert len(repository.list_leave_requests("EMP-001")) == 1


def test_repository_state_is_scoped_by_employee(repository: MemoryRepository) -> None:
    saved_proposal = proposal()
    repository.save_proposal("EMP-001", saved_proposal)
    repository.confirm_proposal("EMP-001", "AP-TEST", "idem-12345678")
    trace = {
        "trace_id": "trace-001",
        "employee_id": "EMP-001",
        "message": "user@example.com",
    }
    repository.save_trace(trace)
    ticket_id = repository.create_ticket("EMP-001", "privacy", "Nomor 081234567890")

    assert repository.get_balances("EMP-002")
    assert repository.list_leave_requests("EMP-002") == []
    assert repository.get_proposal("AP-TEST") == ("EMP-001", saved_proposal)
    assert repository.get_trace("trace-001")["employee_id"] == "EMP-001"
    assert repository.tickets[ticket_id]["employee_id"] == "EMP-001"
    assert "user@example.com" not in repository.get_trace("trace-001")["message"]
    assert "081234567890" not in repository.tickets[ticket_id]["summary"]


def test_concurrent_confirmation_creates_one_request(repository: MemoryRepository) -> None:
    repository.save_proposal("EMP-001", proposal())

    def confirm() -> object:
        try:
            return repository.confirm_proposal("EMP-001", "AP-TEST", "idem-12345678")
        except ConflictError:
            return None

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: confirm(), range(2)))

    assert sum(result is not None for result in results) == 2
    assert len(repository.list_leave_requests("EMP-001")) == 1
    assert all(result.status == "pending_manager_review" for result in results if result is not None)
