"""Opik (Comet ML) Observability & Hierarchical Tracing Adapter.

Provides resilient, non-blocking tracing with strict PII/medical redaction
and graceful fail-open fallback for HR Policy and Leave Assistant.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
import json
import logging
import os
import threading
import time
from typing import Any, Callable, Protocol

from .config import Settings
from .contracts import AuthContext, PolicyChunk
from .domain import estimate_cost
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

def _serialize_for_opik(value: Any) -> Any:
    """Convert Pydantic/SDK objects to JSON-safe primitives and summarize PolicyChunks."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, PolicyChunk):
        return {
            "document_id": value.document_id,
            "version": value.version,
            "section": value.section,
        }
    if hasattr(value, "model_dump") and callable(value.model_dump):
        try:
            dumped = value.model_dump(mode="json")
        except TypeError:
            dumped = value.model_dump()
        return _serialize_for_opik(dumped)
    if isinstance(value, dict):
        return {key: _serialize_for_opik(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        items = list(value)
        if items and all(isinstance(item, PolicyChunk) for item in items):
            return [
                {
                    "document_id": item.document_id,
                    "version": item.version,
                    "section": item.section,
                }
                for item in items
            ]
        return [_serialize_for_opik(item) for item in items]
    if hasattr(value, "to_dict") and callable(value.to_dict):
        return _serialize_for_opik(value.to_dict())
    return str(value)


def _extract_text_from_content(content: Any) -> str:
    """Extract readable text from a message content string or structured parts list."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for part in content:
            if isinstance(part, str):
                parts.append(part)
            elif isinstance(part, dict):
                text = part.get("text")
                if isinstance(text, str) and text:
                    parts.append(text)
            else:
                text = getattr(part, "text", None)
                if isinstance(text, str) and text:
                    parts.append(text)
        return " ".join(parts)
    return str(content)


def _extract_latest_turn_preview(input_data: Any) -> str:
    """Extract only the latest user message or function_call_output string, capped at 300 chars."""
    if input_data is None:
        return ""
    if isinstance(input_data, str):
        return input_data[:300]

    items = list(input_data) if isinstance(input_data, (list, tuple)) else [input_data]
    for item in reversed(items):
        if isinstance(item, dict):
            item_type = item.get("type")
            item_role = item.get("role")
            if item_type == "function_call_output":
                output = item.get("output")
                if output is not None:
                    text = (
                        output
                        if isinstance(output, str)
                        else (
                            json.dumps(_serialize_for_opik(output), ensure_ascii=False)
                            if isinstance(output, (dict, list))
                            else str(output)
                        )
                    )
                    return text[:300]
            elif item_role == "user":
                return _extract_text_from_content(item.get("content"))[:300]
        else:
            item_type = getattr(item, "type", None)
            item_role = getattr(item, "role", None)
            if item_type == "function_call_output":
                output = getattr(item, "output", None)
                if output is not None:
                    text = (
                        output
                        if isinstance(output, str)
                        else (
                            json.dumps(_serialize_for_opik(output), ensure_ascii=False)
                            if isinstance(output, (dict, list))
                            else str(output)
                        )
                    )
                    return text[:300]
            elif item_role == "user":
                return _extract_text_from_content(getattr(item, "content", None))[:300]
    return ""


class LiveOpikSpan:
    def __init__(
        self,
        trace_obj: Any,
        name: str,
        span_type: str,
        sanitized_input: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
        settings: Settings | None = None,
        start_time: datetime | None = None,
    ) -> None:
        self._trace = trace_obj
        self._name = name
        self._span_type = span_type if span_type in ("general", "tool", "llm") else "general"
        self._sanitized_input = sanitized_input
        self._metadata = dict(metadata) if metadata else {}
        self._settings = settings
        self._start_time = start_time or datetime.now(timezone.utc)
        self._output_data: Any = None
        self._status: str = "ok"
        self._ended: bool = False

    def set_output(self, output: Any, status: str = "ok") -> None:
        self._status = status
        self._output_data = redact_trace(_serialize_for_opik(output))

    def end(self) -> None:
        if self._trace is None or self._ended:
            return
        self._ended = True
        try:
            end_time = datetime.now(timezone.utc)
            if end_time < self._start_time:
                end_time = self._start_time
            kwargs: dict[str, Any] = {
                "name": self._name,
                "type": self._span_type,
                "start_time": self._start_time,
                "end_time": end_time,
            }
            if self._sanitized_input is not None:
                kwargs["input"] = self._sanitized_input
            if self._output_data is not None:
                if isinstance(self._output_data, dict):
                    kwargs["output"] = self._output_data
                    in_tok = self._output_data.get("input_tokens")
                    out_tok = self._output_data.get("output_tokens")
                    if in_tok is not None and out_tok is not None:
                        in_count = int(in_tok)
                        out_count = int(out_tok)
                        kwargs["usage"] = {
                            "prompt_tokens": in_count,
                            "completion_tokens": out_count,
                            "total_tokens": in_count + out_count,
                        }
                        model_name = (
                            self._settings.agent_model
                            if self._settings and self._settings.agent_model
                            else "agent"
                        )
                        kwargs["model"] = model_name
                        kwargs["provider"] = "openai"
                        if self._settings is not None:
                            cost = estimate_cost(
                                in_count,
                                out_count,
                                self._settings.input_cost_per_1m,
                                self._settings.output_cost_per_1m,
                            )
                            if cost is not None:
                                kwargs["total_cost"] = round(cost, 6)
                else:
                    kwargs["output"] = {"result": self._output_data}
            meta = dict(self._metadata)
            if self._status != "ok":
                meta["status"] = self._status
            if meta:
                kwargs["metadata"] = meta
            self._trace.span(**kwargs)
        except Exception as err:
            logger.debug("Failed to record Opik span '%s': %s", self._name, err)

    def __enter__(self) -> LiveOpikSpan:
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        if exc_type is not None and exc_val is not None:
            self._status = "error"
            self._output_data = redact_trace(str(exc_val))
        self.end()


class LiveOpikTrace:
    def __init__(
        self,
        trace_obj: Any,
        client: Any,
        settings: Settings | None = None,
        base_metadata: dict[str, Any] | None = None,
        flush_callback: Callable[[], None] | None = None,
        start_time: datetime | None = None,
        sanitized_input: dict[str, Any] | None = None,
    ) -> None:
        self._trace = trace_obj
        self._client = client
        self._settings = settings
        self._base_metadata: dict[str, Any] = dict(base_metadata) if base_metadata else {}
        self._flush_callback = flush_callback
        self._start_time = start_time or datetime.now(timezone.utc)
        self._sanitized_input = sanitized_input

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
            if span_type == "llm":
                preview = _extract_latest_turn_preview(input_data)
                sanitized_input: dict[str, Any] | None = {
                    "turn": (metadata or {}).get("turn"),
                    "items_count": len(input_data) if isinstance(input_data, list) else 1,
                    "latest_input": redact_trace(preview),
                }
            else:
                serialized_input = _serialize_for_opik(input_data)
                sanitized_input = (
                    redact_trace(serialized_input)
                    if isinstance(serialized_input, dict)
                    else ({"input": redact_trace(serialized_input)} if serialized_input is not None else None)
                )
            sanitized_meta = (
                redact_trace(_serialize_for_opik(metadata))
                if metadata is not None
                else {}
            )
            valid_type = span_type if span_type in ("general", "tool", "llm") else "general"
            return LiveOpikSpan(
                trace_obj=self._trace,
                name=name,
                span_type=valid_type,
                sanitized_input=sanitized_input,
                metadata=sanitized_meta if isinstance(sanitized_meta, dict) else {},
                settings=self._settings,
                start_time=datetime.now(timezone.utc),
            )
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
            sanitized_output = (
                redact_trace(_serialize_for_opik(output_data))
                if output_data is not None
                else None
            )
            meta: dict[str, Any] = {
                "outcome": outcome,
                "citations": citations or [],
            }
            if error:
                meta["error"] = redact_trace(str(error))

            if usage and isinstance(usage, dict):
                in_tok = int(usage.get("input_tokens") or 0)
                out_tok = int(usage.get("output_tokens") or 0)
                meta["input_tokens"] = in_tok
                meta["output_tokens"] = out_tok
                meta["total_tokens"] = in_tok + out_tok
                cost = usage.get("estimated_cost")
                if cost is None and (in_tok or out_tok) and self._settings is not None:
                    computed = estimate_cost(
                        in_tok,
                        out_tok,
                        self._settings.input_cost_per_1m,
                        self._settings.output_cost_per_1m,
                    )
                    if computed is not None:
                        cost = round(computed, 6)
                if cost is not None:
                    meta["cost"] = cost

            # Preserve base trace identity/context fields when updating trace metadata on end()
            merged_metadata = {**self._base_metadata, **meta}
            end_kwargs: dict[str, Any] = {
                "metadata": merged_metadata,
                "tags": [outcome],
            }
            if sanitized_output is not None:
                if isinstance(sanitized_output, dict):
                    end_kwargs["output"] = sanitized_output
                else:
                    end_kwargs["output"] = {"answer": str(sanitized_output)}

            trace_id = getattr(self._trace, "id", None)
            if isinstance(trace_id, str) and trace_id and self._client is not None:
                end_time = datetime.now(timezone.utc)
                if end_time < self._start_time:
                    end_time = self._start_time
                self._client.trace(
                    id=trace_id,
                    name="HR Agent Turn",
                    start_time=self._start_time,
                    end_time=end_time,
                    input=self._sanitized_input,
                    **end_kwargs,
                )
            else:
                self._trace.end(**end_kwargs)
        except Exception as err:
            logger.debug("Failed to finalize Opik trace: %s", err)
        finally:
            if self._flush_callback is not None:
                try:
                    self._flush_callback()
                except Exception as err:
                    logger.debug("Failed to schedule Opik flush: %s", err)

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
        self._flush_lock = threading.Lock()
        self._flush_exec_lock = threading.Lock()
        self._flush_timer: threading.Timer | None = None
        self._flush_delay_seconds: float = 0.5
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
            # Pseudonymized user identifier via stable_safety_id (ADR-004); redact user message
            safety_id = stable_safety_id(auth.employee_id)
            base_metadata: dict[str, Any] = {
                "trace_id": trace_id,
                "role": auth.role,
                "safety_identifier": safety_id,
                "environment": self.settings.environment,
                "model": self.settings.agent_model or "agent",
            }

            sanitized_input = {
                "message": redact_trace(user_message),
                "history_length": len(history or []),
            }
            start_time = datetime.now(timezone.utc)
            trace_obj = self.client.trace(
                name="HR Agent Turn",
                start_time=start_time,
                input=sanitized_input,
                metadata=dict(base_metadata),
                tags=[auth.role, self.settings.environment],
            )
            return LiveOpikTrace(
                trace_obj,
                self.client,
                settings=self.settings,
                base_metadata=base_metadata,
                flush_callback=self._schedule_flush,
                start_time=start_time,
                sanitized_input=sanitized_input,
            )
        except Exception as err:
            logger.warning("Failed to start Opik trace: %s", err)
            return NullTrace()

    def _schedule_flush(self) -> None:
        if self.client is None:
            return
        with self._flush_lock:
            if self._flush_timer is not None:
                self._flush_timer.cancel()
            timer = threading.Timer(self._flush_delay_seconds, self._run_scheduled_flush)
            timer.daemon = True
            self._flush_timer = timer
            timer.start()

    def _run_scheduled_flush(self) -> None:
        current = threading.current_thread()
        with self._flush_lock:
            if self._flush_timer is current:
                self._flush_timer = None
        self._flush_client()

    def _flush_client(self) -> None:
        client = self.client
        if client is None or not hasattr(client, "flush"):
            return
        with self._flush_exec_lock:
            try:
                client.flush()
            except Exception as err:
                logger.debug("Error flushing Opik client: %s", err)

    def flush(self) -> None:
        with self._flush_lock:
            if self._flush_timer is not None:
                self._flush_timer.cancel()
                self._flush_timer = None
        if self.client is not None:
            self._flush_client()
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
