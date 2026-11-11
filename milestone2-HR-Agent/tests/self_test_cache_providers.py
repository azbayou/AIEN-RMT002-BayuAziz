from __future__ import annotations

import json
from unittest.mock import MagicMock, patch
import pytest
import redis

from src.cache import NullCache, ResilientCache
from src.contracts import ModelTurn
from src.providers import DeterministicProvider, OpenAIProvider
from src.security import token_hash


# ==============================================================================
# WBS-05: Cache Verification (ResilientCache & NullCache)
# ==============================================================================


def test_null_cache_behavior() -> None:
    cache = NullCache()
    assert cache.health() is False
    assert cache.get("any_key") is None
    assert cache.set("any_key", {"data": 123}, 60) is None


def test_resilient_cache_health() -> None:
    cache = ResilientCache("redis://localhost:6379/0")

    with patch.object(cache.client, "ping", return_value=True):
        assert cache.health() is True

    with patch.object(cache.client, "ping", side_effect=redis.ConnectionError("Connection refused")):
        assert cache.health() is False


def test_resilient_cache_get_and_set() -> None:
    cache = ResilientCache("redis://localhost:6379/0")

    # Hit
    with patch.object(cache.client, "get", return_value=json.dumps({"key": "value"}).encode("utf-8")):
        assert cache.get("test_key") == {"key": "value"}

    # Miss
    with patch.object(cache.client, "get", return_value=None):
        assert cache.get("test_key") is None

    # Corrupt JSON -> degrades to miss
    with patch.object(cache.client, "get", return_value=b"not valid json {"):
        assert cache.get("test_key") is None

    # Redis error -> degrades to miss
    with patch.object(cache.client, "get", side_effect=redis.TimeoutError("Timeout")):
        assert cache.get("test_key") is None

    # Set with valid TTL
    with patch.object(cache.client, "setex") as mock_setex:
        cache.set("test_key", {"a": 1}, ttl_seconds=300)
        mock_setex.assert_called_once_with("test_key", 300, '{"a":1}')

    # Set with non-positive TTL -> no-op
    with patch.object(cache.client, "setex") as mock_setex:
        cache.set("test_key", {"a": 1}, ttl_seconds=0)
        mock_setex.assert_not_called()

    # Set failure on Redis error -> silent fail
    with patch.object(cache.client, "setex", side_effect=redis.ConnectionError("Offline")):
        cache.set("test_key", {"a": 1}, ttl_seconds=300)  # must not raise


# ==============================================================================
# WBS-06: Providers Verification (DeterministicProvider & OpenAIProvider)
# ==============================================================================


def test_deterministic_provider_embeddings() -> None:
    provider = DeterministicProvider(embedding_dimensions=16)
    texts = ["Cuti tahunan", "Kebijakan lembur"]
    embeddings = provider.embed(texts)

    assert len(embeddings) == 2
    assert len(embeddings[0]) == 16
    assert len(embeddings[1]) == 16
    assert all(isinstance(v, float) for v in embeddings[0])
    # Deterministic check
    assert embeddings[0] == provider.embed(["Cuti tahunan"])[0]


def test_deterministic_provider_responses() -> None:
    provider = DeterministicProvider()

    # Query containing "saldo"
    turn_saldo = provider.respond(input_data="Berapa sisa saldo cuti saya?")
    assert len(turn_saldo.tool_calls) == 1
    assert turn_saldo.tool_calls[0].name == "get_my_leave_balance"

    # Query containing "cuti"
    turn_cuti = provider.respond(input_data="Bagaimana kebijakan cuti tahunan?")
    assert len(turn_cuti.tool_calls) == 1
    assert turn_cuti.tool_calls[0].name == "search_hr_policy"

    # Query after tool output with document_id
    tool_input = [
        "Bagaimana cuti tahunan?",
        {"tool_call_id": "call-1", "content": '{"document_id": "HR-LEAVE-001"}'},
    ]
    turn_answer = provider.respond(input_data=tool_input)
    assert "[HR-LEAVE-001]" in turn_answer.text


def test_openai_provider_calls_responses_api_with_store_false_and_hashed_safety() -> None:
    mock_client = MagicMock()

    # Mock response object
    mock_output_item = MagicMock()
    mock_output_item.type = "function_call"
    mock_output_item.name = "search_hr_policy"
    mock_output_item.arguments = '{"query": "cuti", "top_k": 3}'
    mock_output_item.call_id = "call_abc123"

    mock_response = MagicMock()
    mock_response.id = "resp_001"
    mock_response.output = [mock_output_item]
    mock_response.output_text = ""
    mock_response.usage.input_tokens = 42
    mock_response.usage.output_tokens = 18

    mock_client.responses.create.return_value = mock_response

    provider = OpenAIProvider(
        model="gpt-4o-mini",
        embedding_model="text-embedding-3-small",
        client=mock_client,
    )

    turn = provider.respond(
        input_data="Info cuti",
        instructions="System prompt",
        tools=[{"type": "function", "function": {"name": "search_hr_policy"}}],
        safety_identifier="EMP-001",
        max_output_tokens=700,
    )

    # Verify parameters passed to responses.create
    mock_client.responses.create.assert_called_once_with(
        model="gpt-4o-mini",
        input="Info cuti",
        instructions="System prompt",
        tools=[{"type": "function", "function": {"name": "search_hr_policy"}}],
        safety_identifier=token_hash("EMP-001"),
        max_output_tokens=700,
        store=False,
    )

    assert turn.response_id == "resp_001"
    assert len(turn.tool_calls) == 1
    assert turn.tool_calls[0].name == "search_hr_policy"
    assert turn.tool_calls[0].arguments == {"query": "cuti", "top_k": 3}
    assert turn.input_tokens == 42
    assert turn.output_tokens == 18


def test_openai_provider_transient_retry_and_rethrow() -> None:
    mock_client = MagicMock()

    class APITimeoutError(Exception):
        pass

    mock_client.responses.create.side_effect = APITimeoutError("Request timed out")

    provider = OpenAIProvider(
        model="gpt-4o-mini",
        embedding_model="text-embedding-3-small",
        max_retries=2,
        client=mock_client,
    )

    # Should attempt 3 times (attempt 0 + 2 retries) and then re-raise
    with pytest.raises(APITimeoutError):
        provider.respond(
            input_data="Hello",
            instructions="",
            tools=[],
            safety_identifier="EMP-001",
            max_output_tokens=100,
        )

    assert mock_client.responses.create.call_count == 3


def test_openai_provider_batch_embed() -> None:
    mock_client = MagicMock()
    mock_item1 = MagicMock()
    mock_item1.embedding = [0.1, 0.2, 0.3]
    mock_item2 = MagicMock()
    mock_item2.embedding = [0.4, 0.5, 0.6]

    mock_embed_resp = MagicMock()
    mock_embed_resp.data = [mock_item1, mock_item2]
    mock_client.embeddings.create.return_value = mock_embed_resp

    provider = OpenAIProvider(
        model="gpt-4o-mini",
        embedding_model="text-embedding-3-small",
        client=mock_client,
    )

    # Empty list returns [] without calling API
    assert provider.embed([]) == []
    mock_client.embeddings.create.assert_not_called()

    # Non-empty list
    result = provider.embed(["text1", "text2"])
    assert result == [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]
    mock_client.embeddings.create.assert_called_once_with(
        model="text-embedding-3-small",
        input=["text1", "text2"],
    )


def test_provider_transcribe_deterministic_and_openai() -> None:
    # 1. DeterministicProvider tests
    det_provider = DeterministicProvider()
    with pytest.raises(ValueError, match="audio payload must not be empty"):
        det_provider.transcribe(b"")

    res_default = det_provider.transcribe(b"RIFF....WAVE")
    assert res_default == "Berapa sisa saldo cuti tahunan saya?"

    res_prompt = det_provider.transcribe(b"PROMPT:Siapkan cuti besok")
    assert res_prompt == "Siapkan cuti besok"

    # 2. OpenAIProvider with mock client
    mock_client = MagicMock()
    mock_transcription_resp = MagicMock()
    mock_transcription_resp.text = "Berapa jatah cuti melahirkan?"
    mock_client.audio.transcriptions.create.return_value = mock_transcription_resp

    openai_provider = OpenAIProvider(
        model="gpt-4o-mini",
        embedding_model="text-embedding-3-small",
        stt_model="whisper-1",
        client=mock_client,
    )

    with pytest.raises(ValueError, match="audio payload must not be empty"):
        openai_provider.transcribe(b"")

    audio_data = b"MOCK_WAV_BYTES_DATA_FOR_TESTING"
    transcript = openai_provider.transcribe(audio_data, filename="sample.wav", language="id")

    assert transcript == "Berapa jatah cuti melahirkan?"
    mock_client.audio.transcriptions.create.assert_called_once()
    call_kwargs = mock_client.audio.transcriptions.create.call_args.kwargs
    assert call_kwargs["model"] == "whisper-1"
    assert call_kwargs["language"] == "id"
    assert call_kwargs["file"].name == "sample.wav"
    assert call_kwargs["file"].getvalue() == audio_data
