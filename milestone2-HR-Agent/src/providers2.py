from __future__ import annotations

import hashlib
import json
from typing import Any, Protocol

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_openai import ChatOpenAI, OpenAIEmbeddings

from .contracts import ModelTurn
from .security import token_hash


class ModelProvider(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]: ...
    def respond(
        self, *, input_data: str | list[Any], instructions: str,
        tools: list[dict[str, Any]],
        safety_identifier: str, max_output_tokens: int,
    ) -> ModelTurn: ...


class LangChainOpenAIProvider:
    """OpenAI provider implementation utilizing LangChain (ChatOpenAI and OpenAIEmbeddings)."""

    def __init__(self, **kwargs: Any) -> None:
        self.model = kwargs.pop("model")
        self.embedding_model = kwargs.pop("embedding_model")
        self.max_retries = kwargs.pop("max_retries", 2)
        api_key = kwargs.pop("api_key", None)

        self.embeddings = OpenAIEmbeddings(
            model=self.embedding_model,
            max_retries=self.max_retries,
            **( {"api_key": api_key} if api_key else {} ),
            **kwargs,
        )

        self._base_chat_model = ChatOpenAI(
            model=self.model,
            max_retries=self.max_retries,
            **( {"api_key": api_key} if api_key else {} ),
            **kwargs,
        )

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        return self.embeddings.embed_documents(texts)

    def _convert_input_to_messages(
        self, input_data: str | list[Any], instructions: str
    ) -> list[BaseMessage]:
        messages: list[BaseMessage] = []
        if instructions:
            messages.append(SystemMessage(content=instructions))

        if isinstance(input_data, str):
            messages.append(HumanMessage(content=input_data))
        elif isinstance(input_data, list):
            for item in input_data:
                if isinstance(item, BaseMessage):
                    messages.append(item)
                elif isinstance(item, dict):
                    role = item.get("role")
                    content = item.get("content", "")
                    if role == "system":
                        messages.append(SystemMessage(content=content))
                    elif role == "user":
                        messages.append(HumanMessage(content=content))
                    elif role == "assistant":
                        tool_calls = item.get("tool_calls", [])
                        messages.append(AIMessage(content=content, tool_calls=tool_calls))
                    elif role == "tool":
                        messages.append(
                            ToolMessage(
                                content=content,
                                tool_call_id=item.get("tool_call_id", item.get("call_id", "")),
                            )
                        )
                    else:
                        messages.append(HumanMessage(content=str(item)))
                else:
                    messages.append(HumanMessage(content=str(item)))
        return messages

    def respond(
        self, *, input_data: str | list[Any], instructions: str,
        tools: list[dict[str, Any]],
        safety_identifier: str, max_output_tokens: int,
    ) -> ModelTurn:
        # Pass safety_identifier hash as part of model invocation kwargs
        extra_body = {"safety_identifier": token_hash(safety_identifier)}
        llm = self._base_chat_model.bind(max_tokens=max_output_tokens, extra_body=extra_body)

        if tools:
            # Bind tools schema
            llm = llm.bind_tools(tools)

        messages = self._convert_input_to_messages(input_data, instructions)
        response: AIMessage = llm.invoke(messages)

        # Parse tool calls from LangChain's unified tool_calls format
        tool_calls = []
        for tc in getattr(response, "tool_calls", []) or []:
            tool_calls.append(
                {
                    "call_id": tc.get("id", ""),
                    "name": tc.get("name", ""),
                    "arguments": tc.get("args", {}),
                }
            )

        # Extract usage metadata
        usage_metadata = getattr(response, "usage_metadata", None) or {}
        response_metadata = getattr(response, "response_metadata", {}) or {}
        token_usage = response_metadata.get("token_usage", {})

        input_tokens = (
            usage_metadata.get("input_tokens")
            or token_usage.get("prompt_tokens")
            or 0
        )
        output_tokens = (
            usage_metadata.get("output_tokens")
            or token_usage.get("completion_tokens")
            or 0
        )

        response_id = getattr(response, "id", "") or response_metadata.get("id", "")

        return ModelTurn(
            response_id=response_id,
            text=response.content if isinstance(response.content, str) else "",
            tool_calls=tool_calls,
            output_items=[response],
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )


# Alias for drop-in compatibility with OpenAIProvider
OpenAIProvider = LangChainOpenAIProvider


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

