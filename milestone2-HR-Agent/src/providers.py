from __future__ import annotations

import hashlib
import json
import time
from typing import Any, Protocol

from openai import OpenAI

from .contracts import ModelTurn
from .security import token_hash


class ModelProvider(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]: ...
    def respond(
        self, *, input_data: str | list[Any], instructions: str,
        tools: list[dict[str, Any]],
        safety_identifier: str, max_output_tokens: int,
    ) -> ModelTurn: ...


class OpenAIProvider:
    """OpenAI Responses and embeddings adapter with bounded transient retries."""

    def __init__(self, **kwargs: Any) -> None:
        self.model = kwargs.pop("model")
        self.embedding_model = kwargs.pop("embedding_model")
        self.max_retries = kwargs.pop("max_retries", 2)
        self.client = kwargs.pop("client", None) or OpenAI(**kwargs)

    @staticmethod
    def _transient(error: Exception) -> bool:
        name = type(error).__name__
        return name in {"APIConnectionError", "APITimeoutError", "InternalServerError", "RateLimitError"}

    def _call(self, operation, *args: Any, **kwargs: Any) -> Any:
        for attempt in range(self.max_retries + 1):
            try:
                return operation(*args, **kwargs)
            except Exception as error:
                if not self._transient(error) or attempt >= self.max_retries:
                    raise
                time.sleep(0.1 * (attempt + 1))

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        response = self._call(
            self.client.embeddings.create,
            model=self.embedding_model,
            input=texts,
        )
        return [list(item.embedding) for item in response.data]

    def respond(
        self, *, input_data: str | list[Any], instructions: str,
        tools: list[dict[str, Any]],
        safety_identifier: str, max_output_tokens: int,
    ) -> ModelTurn:
        response = self._call(
            self.client.responses.create,
            model=self.model,
            input=input_data,
            instructions=instructions,
            tools=tools,
            safety_identifier=token_hash(safety_identifier),
            max_output_tokens=max_output_tokens,
            store=False,
        )
        tool_calls = []
        for item in getattr(response, "output", []) or []:
            if getattr(item, "type", None) == "function_call":
                arguments = getattr(item, "arguments", "{}")
                tool_calls.append(
                    {
                        "call_id": getattr(item, "call_id", getattr(item, "id", "")),
                        "name": item.name,
                        "arguments": json.loads(arguments),
                    }
                )
        usage = getattr(response, "usage", None)
        return ModelTurn(
            response_id=response.id,
            text=getattr(response, "output_text", "") or "",
            tool_calls=tool_calls,
            output_items=getattr(response, "output", []) or [],
            input_tokens=getattr(usage, "input_tokens", 0) if usage else 0,
            output_tokens=getattr(usage, "output_tokens", 0) if usage else 0,
        )


class DeterministicProvider:
    """Network-free provider used by deterministic tests."""

    def __init__(self, embedding_dimensions: int = 8) -> None:
        self.embedding_dimensions = embedding_dimensions
        self._response_number = 0

    def embed(self, texts: list[str]) -> list[list[float]]:
        vectors = []
        for text in texts:
            digest = hashlib.sha256(text.encode("utf-8")).digest()
            values = [digest[index] / 255.0 for index in range(self.embedding_dimensions)]
            vectors.append(values)
        return vectors

    def respond(self, **kwargs: Any) -> ModelTurn:
        self._response_number += 1
        input_data = kwargs.get("input_data", "")
        text = input_data if isinstance(input_data, str) else json.dumps(input_data)
        lowered = text.casefold()
        if isinstance(input_data, list) and any(
            isinstance(item, dict) and "tool_call_id" in item for item in input_data
        ):
            if "document_id" in text:
                return ModelTurn(
                    response_id=f"deterministic-{self._response_number}",
                    text="Berdasarkan kebijakan yang ditemukan, berikut jawabannya. [HR-LEAVE-001]",
                    input_tokens=len(text.split()),
                    output_tokens=8,
                )
            return ModelTurn(
                response_id=f"deterministic-{self._response_number}",
                text="Berikut informasi yang tersedia untuk identitas Anda.",
                input_tokens=len(text.split()),
                output_tokens=7,
            )
        if "saldo" in lowered:
            tool_calls = [{"call_id": f"call-{self._response_number}", "name": "get_my_leave_balance", "arguments": {}}]
        elif any(term in lowered for term in ("cuti", "kebijakan", "jatah", "leave")):
            tool_calls = [{
                "call_id": f"call-{self._response_number}",
                "name": "search_hr_policy",
                "arguments": {"query": text[:500], "top_k": 3},
            }]
        else:
            tool_calls = []
        return ModelTurn(
            response_id=f"deterministic-{self._response_number}",
            text="" if tool_calls else "Saya belum memiliki bukti yang cukup untuk menjawab.",
            tool_calls=tool_calls,
            input_tokens=len(text.split()),
            output_tokens=0,
        )
