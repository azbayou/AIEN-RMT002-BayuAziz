"""Opik (Comet ML) Observability & Hierarchical Tracing Adapter.

Provides resilient, non-blocking tracing with strict PII/medical redaction
and graceful fail-open fallback for HR Policy and Leave Assistant.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
import json
import logging
import threading
import time
from typing import Any, Callable, Protocol
from urllib.parse import urlparse

from .config import Settings
from .contracts import AuthContext
from .domain import estimate_cost
from .security import redact, stable_safety_id

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
# Live Opik SDK Wrapper (Strictly Metadata-Only Telemetry)
# ---------------------------------------------------------------------------

def _derive_provider_label(settings: Settings | None) -> str:
    if settings is None or not settings.openai_base_url:
        return "openai"
    host = (urlparse(settings.openai_base_url).hostname or "").casefold()
    if not host or "openai.com" in host:
        return "openai"
    return host


def _metadata_only_span_output(span_type: str, output: Any, status: str) -> dict[str, Any]:
    if span_type == "llm" and isinstance(output, dict):
        return {
            "tool_calls_count": int(output.get("tool_calls_count") or 0),
            "input_tokens": int(output.get("input_tokens") or 0),
            "output_tokens": int(output.get("output_tokens") or 0),
        }
    summary: dict[str, Any] = {
        "status": status,
        "result_type": type(output).__name__ if output is not None else "NoneType",
    }
    if isinstance(output, (list, tuple, set)):
        summary["item_count"] = len(output)
    return summary


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
        self._output_data: dict[str, Any] | None = None
        self._status: str = "ok"
        self._ended: bool = False

    def set_output(self, output: Any, status: str = "ok") -> None:
        self._status = status
        self._output_data = _metadata_only_span_output(self._span_type, output, status)

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
                    kwargs["provider"] = _derive_provider_label(self._settings)
                    if self._settings is not None:
                        cost = estimate_cost(
                            in_count,
                            out_count,
                            self._settings.input_cost_per_1m,
                            self._settings.output_cost_per_1m,
                        )
                        if cost is not None:
                            kwargs["total_cost"] = round(cost, 6)
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
            self._output_data = {
                "status": "error",
                "result_type": type(exc_val).__name__,
                "error": redact(str(exc_val)),
            }
        self.end()


class LiveOpikTrace:
    def __init__(
        self,
        trace_obj: Any,
        client: Any,
        settings: Settings | None = None,
        base_metadata: dict[str, Any] | None = None,
        base_tags: list[str] | None = None,
        flush_callback: Callable[[], None] | None = None,
        start_time: datetime | None = None,
        sanitized_input: dict[str, Any] | None = None,
    ) -> None:
        self._trace = trace_obj
        self._client = client
        self._settings = settings
        self._base_metadata: dict[str, Any] = dict(base_metadata) if base_metadata else {}
        self._base_tags: list[str] = list(base_tags) if base_tags else []
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
            valid_type = span_type if span_type in ("general", "tool", "llm") else "general"
            meta_dict = dict(metadata) if isinstance(metadata, dict) else {}
            if valid_type == "llm":
                sanitized_input: dict[str, Any] | None = {
                    "turn": meta_dict.get("turn"),
                    "role": meta_dict.get("role"),
                    "message_count": len(input_data) if isinstance(input_data, (list, tuple)) else 1,
                }
            elif valid_type == "tool":
                sanitized_input = {
                    "arg_keys": sorted(str(k) for k in input_data.keys())
                    if isinstance(input_data, dict)
                    else [],
                }
            else:
                sanitized_input = {
                    "input_type": type(input_data).__name__ if input_data is not None else "NoneType",
                }
            sanitized_meta = {
                str(k): redact(v) if isinstance(v, str) else v
                for k, v in meta_dict.items()
                if k in {"turn", "role", "call_id"}
            }
            return LiveOpikSpan(
                trace_obj=self._trace,
                name=name,
                span_type=valid_type,
                sanitized_input=sanitized_input,
                metadata=sanitized_meta,
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
            citation_list = list(citations or [])
            safe_error = redact(str(error)) if error else None
            meta: dict[str, Any] = {
                "outcome": outcome,
                "citations": citation_list,
            }
            if safe_error:
                meta["error"] = safe_error

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

            merged_metadata = {**self._base_metadata, **meta}
            merged_tags = list(dict.fromkeys([*self._base_tags, outcome]))
            metadata_output: dict[str, Any] = {
                "outcome": outcome,
                "answer_length": len(str(output_data or "")),
                "citations": citation_list,
                "error": safe_error,
            }
            end_kwargs: dict[str, Any] = {
                "metadata": merged_metadata,
                "tags": merged_tags,
                "output": metadata_output,
            }

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
            safety_id = stable_safety_id(auth.employee_id)
            base_metadata: dict[str, Any] = {
                "trace_id": trace_id,
                "role": auth.role,
                "safety_identifier": safety_id,
                "environment": self.settings.environment,
                "model": self.settings.agent_model or "agent",
            }
            base_tags = [auth.role, self.settings.environment]
            sanitized_input = {
                "message_length": len(user_message or ""),
                "history_turns": len(history or []),
                "role": auth.role,
                "employee_hash": safety_id,
            }
            start_time = datetime.now(timezone.utc)
            trace_obj = self.client.trace(
                name="HR Agent Turn",
                start_time=start_time,
                input=sanitized_input,
                metadata=dict(base_metadata),
                tags=list(base_tags),
            )
            return LiveOpikTrace(
                trace_obj,
                self.client,
                settings=self.settings,
                base_metadata=base_metadata,
                base_tags=base_tags,
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
