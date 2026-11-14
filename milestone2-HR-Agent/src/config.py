from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "HR Policy and Leave Assistant"
    environment: str = "development"
    database_url: str = ""
    redis_url: str | None = "redis://redis:6379/0"
    openai_api_key: str | None = None
    openai_base_url: str | None = None
    gemini_api_key: str | None = None
    gemini_stt_model: str = "gemini-3.5-transcribe"
    agent_model: str = ""
    embedding_model: str = ""
    stt_model: str = "whisper-1"
    embedding_dimensions: int = Field(default=1536, ge=64, le=4096)
    policy_index_version: str = "policies-2026-01"
    model_mode: Literal["live", "fake"] = "live"
    max_agent_turns: int = Field(default=4, ge=1, le=8)
    max_tool_calls: int = Field(default=6, ge=1, le=12)
    max_output_tokens: int = Field(default=700, ge=128, le=4096)
    model_timeout_seconds: float = Field(default=30.0, ge=1, le=120)
    proposal_ttl_minutes: int = Field(default=15, ge=1, le=60)
    retrieval_cache_ttl_seconds: int = Field(default=900, ge=0, le=86400)
    input_cost_per_1m: float | None = Field(default=None, ge=0)
    output_cost_per_1m: float | None = Field(default=None, ge=0)
    opik_api_key: str | None = None
    opik_workspace: str | None = None
    opik_project_name: str = "Milestone 2 - HR Agent"
    opik_enabled: bool = True

    @field_validator(
        "openai_api_key",
        "openai_base_url",
        "gemini_api_key",
        "opik_api_key",
        "opik_workspace",
        "input_cost_per_1m",
        "output_cost_per_1m",
        "redis_url",
        mode="before",
    )
    @classmethod
    def empty_string_is_none(cls, value):
        return None if isinstance(value, str) and not value.strip() else value

    @field_validator("app_name", "environment", "policy_index_version", mode="before")
    @classmethod
    def non_blank_text(cls, value):
        if not isinstance(value, str) or not value.strip():
            raise ValueError("configuration value must not be blank")
        return value.strip()

    @field_validator("database_url", mode="before")
    @classmethod
    def valid_database_url(cls, value):
        if not isinstance(value, str) or not value.strip():
            raise ValueError("service URL must not be blank")
        clean = value.strip().strip("'\"")
        if "://" not in clean:
            raise ValueError("service URL must include a scheme")
        return clean

    @field_validator("redis_url", mode="before")
    @classmethod
    def valid_redis_url(cls, value):
        if value is None or (isinstance(value, str) and not value.strip()):
            return None
        if not isinstance(value, str):
            raise ValueError("redis URL must be a string")
        clean = value.strip()
        if "://" not in clean:
            raise ValueError("service URL must include a scheme")
        return clean

    @property
    def live_model_ready(self) -> bool:
        return self.model_mode == "live" and bool(
            self.openai_api_key and self.agent_model and self.embedding_model
        )

    @property
    def configuration_ready(self) -> bool:
        return bool(self.database_url) and (
            self.model_mode == "fake" or self.live_model_ready
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
