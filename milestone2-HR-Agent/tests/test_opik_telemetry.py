"""Tests for Opik observability, hierarchical tracing, and PII/medical redaction."""
from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from src.agent import AgentService
from src.config import Settings
from src.contracts import AuthContext, ChatRequest
from src.opik_tracker import NullSpan, NullTrace, NullTracker, OpikTracker, create_opik_tracker
from src.providers import DeterministicProvider
from src.repository import MemoryRepository
from src.cache import NullCache
from src.retrieval import RetrievalService
from src.security import stable_safety_id
from src.tools import ToolExecutor


def test_create_opik_tracker_disabled_or_empty_key():
    settings = Settings(opik_enabled=False, opik_api_key="test-key")
    tracker = create_opik_tracker(settings)
    assert isinstance(tracker, NullTracker)

    settings_no_key = Settings(opik_enabled=True, opik_api_key=None)
    tracker_no_key = create_opik_tracker(settings_no_key)
    assert isinstance(tracker_no_key, NullTracker)


def test_create_opik_tracker_fake_mode():
    settings = Settings(model_mode="fake", opik_enabled=True, opik_api_key="test-key")
    tracker = create_opik_tracker(settings)
    assert isinstance(tracker, NullTracker)


def test_null_tracker_interface():
    tracker = NullTracker()
    auth = AuthContext(employee_id="EMP-001", display_name="Test User", role="employee")
    trace = tracker.trace_turn("trace-123", "Halo", auth)
    assert isinstance(trace, NullTrace)

    span = trace.span("test-span")
    assert isinstance(span, NullSpan)

    # Should execute without errors
    with span as s:
        s.set_output({"status": "ok"})
    trace.end(output_data="Done", outcome="answered")
    tracker.flush()


def test_opik_tracker_redaction_and_safety_id():
    mock_client = MagicMock()
    mock_trace_obj = MagicMock()
    mock_span_obj = MagicMock()
    mock_trace_obj.span.return_value = mock_span_obj
    mock_client.trace.return_value = mock_trace_obj

    settings = Settings(
        opik_enabled=True,
        opik_api_key="mock-api-key",
        opik_workspace="test-workspace",
        opik_project_name="Test Project",
        model_mode="live",
    )

    with patch("opik.Opik", return_value=mock_client):
        tracker = OpikTracker(settings)
        auth = AuthContext(employee_id="EMP-100", display_name="Budi", role="employee")

        # Test medical term & token redaction in prompt
        prompt_with_pii = "Saya mengidap diabetes dan butuh cuti. Token saya secret-abc12345"
        trace = tracker.trace_turn("trace-999", prompt_with_pii, auth)

        mock_client.trace.assert_called_once()
        trace_call_args = mock_client.trace.call_args[1]
        
        # Verify pseudonymized employee_id (safety_id)
        assert trace_call_args["metadata"]["safety_identifier"] == stable_safety_id("EMP-100")
        assert trace_call_args["metadata"]["role"] == "employee"

        # Verify prompt message has medical term and token redacted
        sanitized_input = trace_call_args["input"]["message"]
        assert "diabetes" not in sanitized_input
        assert "[REDACTED_MEDICAL]" in sanitized_input
        assert "secret-abc12345" not in sanitized_input
        assert "[REDACTED_TOKEN]" in sanitized_input

        # Test span input redaction
        with trace.span("tool:test", span_type="tool", input_data={"detail": "kondisi medis: asma"}) as sp:
            sp.set_output({"result": "diagnosa: covid-19 selesai"})

        span_call_args = mock_trace_obj.span.call_args[1]
        assert "[REDACTED_MEDICAL]" in str(span_call_args["input"])
        assert "asma" not in str(span_call_args["input"])

        end_span_args = mock_span_obj.end.call_args[1]
        assert "[REDACTED_MEDICAL]" in str(end_span_args["output"])
        assert "covid-19" not in str(end_span_args["output"])

        # End trace with medical answer
        trace.end(output_data="Surat dokter menyatakan pasien diabetes akut", outcome="answered")
        trace_end_args = mock_trace_obj.end.call_args[1]
        assert "[REDACTED_MEDICAL]" in str(trace_end_args["output"])
        assert "diabetes" not in str(trace_end_args["output"])


def test_agent_service_with_null_tracker(repository: MemoryRepository):
    provider = DeterministicProvider()
    settings = Settings(model_mode="fake", opik_enabled=False)
    cache = NullCache()
    retrieval = RetrievalService(repository, provider, cache, 0)
    tools = ToolExecutor(repository, retrieval, settings)
    agent = AgentService(repository, provider, tools, settings)

    auth = repository.authenticate("token-alya")
    assert auth is not None

    req = ChatRequest(message="Berapa jatah cuti tahunan menurut kebijakan?")
    res = agent.run(req, auth)

    assert res.outcome.value in ("answered", "abstained", "action_proposed")
    assert res.trace_id.startswith("trace-")
    assert res.answer is not None
