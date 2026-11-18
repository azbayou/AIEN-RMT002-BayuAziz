from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import re
import time
from typing import Any, Protocol

import httpx
from openai import OpenAI

from .contracts import ModelToolCall, ModelTurn
from .security import token_hash


class ModelProvider(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]: ...
    def respond(
        self, *, input_data: str | list[Any], instructions: str,
        tools: list[dict[str, Any]],
        safety_identifier: str, max_output_tokens: int,
    ) -> ModelTurn: ...
    def transcribe(self, audio_bytes: bytes, filename: str = "recording.wav", language: str = "id") -> str: ...


class OpenAIProvider:
    """OpenAI Responses and embeddings adapter with bounded transient retries."""

    def __init__(self, **kwargs: Any) -> None:
        self.model = kwargs.pop("model")
        self.embedding_model = kwargs.pop("embedding_model")
        self.stt_model = kwargs.pop("stt_model", "whisper-1")
        self.gemini_api_key = kwargs.pop("gemini_api_key", None)
        self.gemini_stt_model = kwargs.pop("gemini_stt_model", "gemini-2.5-flash")
        self.max_retries = kwargs.pop("max_retries", 2)
        client = kwargs.pop("client", None)
        base_url = kwargs.pop("base_url", None)
        if client is not None:
            self.client = client
        else:
            if base_url and isinstance(base_url, str) and base_url.strip():
                kwargs["base_url"] = base_url.strip()
            elif not (os.environ.get("OPENAI_BASE_URL") or "").strip():
                kwargs["base_url"] = "https://api.openai.com/v1"
            self.client = OpenAI(**kwargs)

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
                raw_args = getattr(item, "arguments", "{}")
                if isinstance(raw_args, dict):
                    parsed_args = raw_args
                elif isinstance(raw_args, str):
                    try:
                        parsed_args = json.loads(raw_args) if raw_args.strip() else {}
                    except json.JSONDecodeError:
                        parsed_args = {}
                    if not isinstance(parsed_args, dict):
                        parsed_args = {}
                else:
                    parsed_args = {}
                tool_calls.append(
                    {
                        "call_id": getattr(item, "call_id", getattr(item, "id", "")),
                        "name": item.name,
                        "arguments": parsed_args,
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

    def _transcribe_with_gemini(self, audio_bytes: bytes, filename: str = "recording.wav", language: str = "id") -> str:
        # Detect audio container and format from magic bytes or extension
        if audio_bytes.startswith(b"\x1a\x45\xdf\xa3") or "webm" in (filename or "").lower():
            mime_type = "audio/webm"
        elif audio_bytes.startswith(b"OggS") or "ogg" in (filename or "").lower():
            mime_type = "audio/ogg"
        elif audio_bytes.startswith(b"ID3") or audio_bytes.startswith(b"\xff\xfb") or "mp3" in (filename or "").lower():
            mime_type = "audio/mp3"
        else:
            mime_type = "audio/wav"

        b64_audio = base64.b64encode(audio_bytes).decode("ascii")

        # Models to try: configured Gemini STT model first, then standard Gemini Flash fallbacks
        models_to_try: list[str] = []
        for candidate in (
            self.gemini_stt_model,
            "gemini-2.5-flash",
            "gemini-2.0-flash",
        ):
            if candidate and isinstance(candidate, str):
                clean_candidate = candidate.strip()
                if clean_candidate and clean_candidate not in models_to_try:
                    models_to_try.append(clean_candidate)

        last_error = None
        for m in models_to_try:
            clean_m = m.replace("models/", "")
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{clean_m}:generateContent"
            headers = {"x-goog-api-key": self.gemini_api_key}
            payload = {
                "contents": [
                    {
                        "parts": [
                            {
                                "text": (
                                    f"Transkripsikan rekaman suara Bahasa {language.upper()} berikut ini secara persis kata demi kata ke dalam teks. "
                                    "Hanya berikan teks transkripsi tanpa pengantar, tanpa tanda kutip, dan tanpa penjelasan tambahan. "
                                    "Jika rekaman hening, hanya bunyi nada/bip, atau tidak ada ucapan kata manusia yang dapat dimengerti, balas persis: [NO_SPEECH]"
                                )
                            },
                            {
                                "inlineData": {
                                    "mimeType": mime_type,
                                    "data": b64_audio,
                                }
                            },
                        ]
                    }
                ]
            }
            try:
                resp = httpx.post(url, json=payload, headers=headers, timeout=25.0)
                if resp.status_code == 200:
                    data = resp.json()
                    candidates = data.get("candidates", [])
                    if candidates:
                        content = candidates[0].get("content")
                        if content and isinstance(content, dict):
                            parts = content.get("parts", [])
                            text = "".join(p.get("text", "") for p in parts if isinstance(p, dict) and "text" in p).strip()
                            if text:
                                clean_text = text.replace("[NO_SPEECH]", "").strip()
                                if clean_text:
                                    return clean_text
                                # Explicitly recognized silence / no speech
                                return ""
                    # If candidates is empty or has no text content, try next candidate model
                    continue
                preview = resp.text[:150]
                if self.gemini_api_key:
                    preview = preview.replace(self.gemini_api_key, "[REDACTED]")
                last_error = f"HTTP {resp.status_code}: {preview}"
                if resp.status_code in (400, 401, 403):
                    break
            except Exception as err:
                msg = str(err)
                if self.gemini_api_key:
                    msg = msg.replace(self.gemini_api_key, "[REDACTED]")
                last_error = msg

        if last_error:
            raise RuntimeError(f"Gemini STT error: {last_error}")
        return ""

    def transcribe(self, audio_bytes: bytes, filename: str = "recording.wav", language: str = "id") -> str:
        if not audio_bytes:
            raise ValueError("audio payload must not be empty")

        gemini_error: str | None = None
        # 1. Attempt Gemini STT if configured
        if self.gemini_api_key:
            try:
                return self._transcribe_with_gemini(audio_bytes, filename=filename, language=language)
            except Exception as err:
                # If Gemini encounters an API/network error, fallback to OpenAI Whisper
                gemini_error = str(err)

        # 2. Primary / Fallback to OpenAI Whisper
        buffer = io.BytesIO(audio_bytes)
        buffer.name = filename or "recording.wav"
        try:
            response = self._call(
                self.client.audio.transcriptions.create,
                model=self.stt_model,
                file=buffer,
                language=language,
            )
            text = getattr(response, "text", "") if not isinstance(response, str) else response
            return str(text).strip()
        except Exception as whisper_err:
            err_msg = str(whisper_err)
            if gemini_error:
                raise RuntimeError(
                    f"Speech-to-text failed (Gemini: {gemini_error}; Whisper: {err_msg})"
                ) from whisper_err
            if "403" in err_msg or "whisper-1" in err_msg:
                raise RuntimeError(
                    f"Speech-to-text service is unavailable: OpenAI whisper-1 permission denied and Gemini STT is not configured ({err_msg})."
                ) from whisper_err
            raise


class DeterministicProvider:
    """Network-free provider used by deterministic tests."""

    def __init__(self, embedding_dimensions: int = 8) -> None:
        self.embedding_dimensions = embedding_dimensions
        self._response_number = 0

    def embed(self, texts: list[str]) -> list[list[float]]:
        vectors = []
        for text in texts:
            digest = hashlib.sha256(text.encode("utf-8")).digest()
            values = [
                ((digest[index % 32] + (index // 32)) % 256) / 255.0
                for index in range(self.embedding_dimensions)
            ]
            vectors.append(values)
        return vectors

    def respond(self, **kwargs: Any) -> ModelTurn:
        self._response_number += 1
        input_data = kwargs.get("input_data", "")
        text = input_data if isinstance(input_data, str) else json.dumps(input_data, default=str)
        user_text = text
        if isinstance(input_data, list):
            for item in reversed(input_data):
                if isinstance(item, dict) and item.get("role") == "user" and isinstance(item.get("content"), str):
                    user_text = item["content"]
                    break
        lowered = user_text.casefold()
        if isinstance(input_data, list) and any(
            isinstance(item, dict) and ("tool_call_id" in item or item.get("type") == "function_call_output")
            for item in input_data
        ):
            if "document_id" in text:
                doc_ids = re.findall(r'document_id\\?":\s*\\?"([A-Za-z0-9-]+)', text)
                cited_doc = doc_ids[0] if doc_ids else "HR-LEAVE-001"
                return ModelTurn(
                    response_id=f"deterministic-{self._response_number}",
                    text=f"Berdasarkan kebijakan yang ditemukan, berikut jawabannya. [{cited_doc}]",
                    input_tokens=len(text.split()),
                    output_tokens=8,
                )
            return ModelTurn(
                response_id=f"deterministic-{self._response_number}",
                text="Berikut informasi yang tersedia untuk identitas Anda.",
                input_tokens=len(text.split()),
                output_tokens=7,
            )
        available_tool_names = {t.get("name") for t in (kwargs.get("tools") or []) if isinstance(t, dict)}
        if any(term in lowered for term in ("analitik", "analytics", "statistik", "tren")) and "get_team_hr_analytics" in available_tool_names:
            tool_calls = [
                ModelToolCall(
                    call_id=f"call-{self._response_number}",
                    name="get_team_hr_analytics",
                    arguments={"metric_focus": "overview"},
                )
            ]
        elif "saldo" in lowered:
            tool_calls = [ModelToolCall(call_id=f"call-{self._response_number}", name="get_my_leave_balance", arguments={})]
        elif any(term in lowered for term in ("cuti", "kebijakan", "jatah", "leave", "wfh", "remote", "probation", "surat", "dokter")):
            tool_calls = [
                ModelToolCall(
                    call_id=f"call-{self._response_number}",
                    name="search_hr_policy",
                    arguments={"query": user_text[:500], "top_k": 3},
                )
            ]
        else:
            tool_calls = []
        return ModelTurn(
            response_id=f"deterministic-{self._response_number}",
            text="" if tool_calls else "Saya belum memiliki bukti yang cukup untuk menjawab.",
            tool_calls=tool_calls,
            input_tokens=len(text.split()),
            output_tokens=0,
        )

    def transcribe(self, audio_bytes: bytes, filename: str = "recording.wav", language: str = "id") -> str:
        if not audio_bytes:
            raise ValueError("audio payload must not be empty")
        # Jika test mengirim teks UTF-8 diawali 'PROMPT:', kembalikan teks tersebut untuk simulasi
        try:
            decoded = audio_bytes.decode("utf-8")
            if decoded.startswith("PROMPT:"):
                return decoded[7:].strip()
        except UnicodeDecodeError:
            pass
        return "Berapa sisa saldo cuti tahunan saya?"
