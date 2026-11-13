"""Opik (Comet ML) Observability & Hierarchical Tracing Adapter.

Provides resilient, non-blocking tracing with strict PII/medical redaction
and graceful fail-open fallback for HR Policy and Leave Assistant.
"""
from __future__ import annotations

import logging
import os
import time
from typing import Any, Protocol

from .config import Settings
from .contracts import AuthContext
from .repository import redact_trace
from .security import stable_safety_id

logger = logging.getLogger("hr_assistant.opik")


class SpanContextProtocol(Protocol):
    def set_output(self, output: Any, status: str = "ok") -> None: ...
    def end(self) -> None: ...
    def __enter__(self) -> SpanContextProtocol: ...
    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None: ...


class TraceContextProtocol(Protocol):
    def span(
        self,
        name: str,
        span_type: str = "general",
        input_data: Any = None,
        metadata: dict[str, Any] | None = None,
    ) -> SpanContextProtocol: ...
    def end(
        self,
        output_data: Any = None,
        outcome: str = "answered",
        usage: dict[str, Any] | None = None,
        citations: list[str] | None = None,
        error: str | None = None,
    ) -> None: ...
    def __enter__(self) -> TraceContextProtocol: ...
    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None: ...


# ---------------------------------------------------------------------------
# No-Op / Fallback implementations
# ---------------------------------------------------------------------------

class NullSpan:
    """No-op span context."""
    def set_output(self, output: Any, status: str = "ok") -> None:
        pass

    def end(self) -> None:
        pass

    def __enter__(self) -> NullSpan:
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        pass


class NullTrace:
    """No-op trace context."""
    def span(
        self,
        name: str,
        span_type: str = "general",
        input_data: Any = None,
        metadata: dict[str, Any] | None = None,
    ) -> SpanContextProtocol:
        return NullSpan()

    def end(
        self,
        output_data: Any = None,
        outcome: str = "answered",
        usage: dict[str, Any] | None = None,
        citations: list[str] | None = None,
        error: str | None = None,
    ) -> None:
        pass

    def __enter__(self) -> NullTrace:
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        pass


class NullTracker:
    """No-op tracker used when Opik is disabled or unconfigured."""
    def trace_turn(
        self,
        trace_id: str,
        user_message: str,
        auth: AuthContext,
        history: list[Any] | None = None,
    ) -> TraceContextProtocol:
        return NullTrace()

    def flush(self) -> None:
        pass


# ---------------------------------------------------------------------------
# Live Opik SDK Wrapper
# ---------------------------------------------------------------------------

class LiveOpikSpan:
    def __init__(self, span_obj: Any) -> None:
        self._span = span_obj
        self._output_data: Any = None
        self._status: str = "ok"

    def set_output(self, output: Any, status: str = "ok") -> None:
        self._status = status
        self._output_data = redact_trace(output)

    def end(self) -> None:
        if self._span is None:
            return
        try:
            kwargs: dict[str, Any] = {}
            if self._output_data is not None:
                if isinstance(self._output_data, dict):
                    kwargs["output"] = self._output_data
                else:
                    kwargs["output"] = {"result": self._output_data}
            if self._status != "ok":
                kwargs["metadata"] = {"status": self._status}
            self._span.end(**kwargs)
        except Exception as err:
            logger.debug("Failed to finalize Opik span: %s", err)

    def __enter__(self) -> LiveOpikSpan:
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        if exc_type is not None and exc_val is not None:
            self._status = "error"
            self._output_data = redact_trace(str(exc_val))
        self.end()


class LiveOpikTrace:
    def __init__(self, trace_obj: Any, client: Any) -> None:
        self._trace = trace_obj
        self._client = client
        self._started = time.monotonic()

    def span(
        self,
        name: str,
        span_type: str = "general",
        input_data: Any = None,
        metadata: dict[str, Any] | None = None,
    ) -> SpanContextProtocol:
        if self._trace is None:
            return NullSpan()
        try:
            sanitized_input = (
                redact_trace(input_data)
                if isinstance(input_data, dict)
                else ({"input": redact_trace(input_data)} if input_data is not None else None)
            )
            sanitized_meta = redact_trace(metadata) if metadata is not None else {}
            # Opik span types: 'general', 'tool', 'llm'
            valid_type = span_type if span_type in ("general", "tool", "llm") else "general"
            span_obj = self._trace.span(
                name=name,
                type=valid_type,
                input=sanitized_input,
                metadata=sanitized_meta or None,
            )
            return LiveOpikSpan(span_obj)
        except Exception as err:
            logger.debug("Failed to create Opik span '%s': %s", name, err)
            return NullSpan()

    def end(
        self,
        output_data: Any = None,
        outcome: str = "answered",
        usage: dict[str, Any] | None = None,
        citations: list[str] | None = None,
        error: str | None = None,
    ) -> None:
        if self._trace is None:
            return
        try:
            sanitized_output = redact_trace(output_data) if output_data is not None else None
            meta: dict[str, Any] = {
                "outcome": outcome,
                "citations": citations or [],
            }
            if error:
                meta["error"] = redact_trace(error)

            end_kwargs: dict[str, Any] = {
                "metadata": meta,
                "tags": [outcome],
            }
            if sanitized_output is not None:
                if isinstance(sanitized_output, dict):
                    end_kwargs["output"] = sanitized_output
                else:
                    end_kwargs["output"] = {"answer": str(sanitized_output)}

            if usage and isinstance(usage, dict) and usage.get("estimated_cost") is not None:
                end_kwargs["metadata"]["cost"] = usage["estimated_cost"]

            self._trace.end(**end_kwargs)
        except Exception as err:
            logger.debug("Failed to finalize Opik trace: %s", err)

    def __enter__(self) -> LiveOpikTrace:
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        if exc_type is not None and exc_val is not None:
            self.end(error=str(exc_val), outcome="error")


class OpikTracker:
    """Production tracker integrating directly with the Opik Python SDK."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.client: Any = None
        self._init_client()

    def _init_client(self) -> None:
        try:
            import opik

            # Explicitly set environment variables so Opik SDK picks them up
            if self.settings.opik_api_key:
                os.environ["OPIK_API_KEY"] = self.settings.opik_api_key
            if self.settings.opik_workspace:
                os.environ["OPIK_WORKSPACE"] = self.settings.opik_workspace
            if self.settings.opik_project_name:
                os.environ["OPIK_PROJECT_NAME"] = self.settings.opik_project_name

            self.client = opik.Opik(
                project_name=self.settings.opik_project_name,
                workspace=self.settings.opik_workspace,
                api_key=self.settings.opik_api_key,
                _use_batching=True,
            )
            logger.info(
                "Opik tracker initialized successfully for project '%s' (workspace '%s')",
                self.settings.opik_project_name,
                self.settings.opik_workspace,
            )
        except Exception as err:
            logger.warning("Could not initialize Opik client (falling back to no-op): %s", err)
            self.client = None

    def trace_turn(
        self,
        trace_id: str,
        user_message: str,
        auth: AuthContext,
        history: list[Any] | None = None,
    ) -> TraceContextProtocol:
        if self.client is None:
            return NullTrace()
        try:
            # Strict Redaction on all input texts
            sanitized_message = redact_trace(user_message)
            sanitized_history = (
                [redact_trace(h.model_dump() if hasattr(h, "model_dump") else h) for h in history]
                if history
                else []
            )
            # Pseudonymized user identifier via stable_safety_id (ADR-004)
            safety_id = stable_safety_id(auth.employee_id)

            trace_obj = self.client.trace(
                name="HR Agent Turn",
                input={
                    "message": sanitized_message,
                    "history_length": len(sanitized_history),
                },
                metadata={
                    "trace_id": trace_id,
                    "role": auth.role,
                    "safety_identifier": safety_id,
                    "environment": self.settings.environment,
                    "model": self.settings.agent_model,
                },
                tags=[auth.role, self.settings.environment],
            )
            return LiveOpikTrace(trace_obj, self.client)
        except Exception as err:
            logger.warning("Failed to start Opik trace: %s", err)
            return NullTrace()

    def flush(self) -> None:
        if self.client is not None:
            try:
                import opik
                opik.flush_tracker()
            except Exception as err:
                logger.debug("Error flushing Opik tracker: %s", err)


def create_opik_tracker(settings: Settings) -> OpikTracker | NullTracker:
    """Factory creating an active OpikTracker or a zero-overhead NullTracker."""
    if not settings.opik_enabled or not settings.opik_api_key:
        logger.info("Opik tracking is disabled or missing API key; using NullTracker.")
        return NullTracker()

    # If running in fake test model mode, use NullTracker to save quota & prevent test delays
    if settings.model_mode == "fake":
        return NullTracker()

    try:
        return OpikTracker(settings)
    except Exception as err:
        logger.warning("Failed to create OpikTracker; defaulting to NullTracker: %s", err)
        return NullTracker()
