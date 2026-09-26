"""Application configuration loaded from environment variables."""

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Shared runtime settings for AI services and workers."""

    app_env: Literal["local", "test", "development", "production"] = "local"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"

    livekit_url: str = "ws://localhost:7880"
    livekit_api_key: SecretStr = SecretStr("")
    livekit_api_secret: SecretStr = SecretStr("")

    openai_api_key: SecretStr = SecretStr("")
    openai_model: Literal["gpt-4o-mini", "gpt-4o"] = "gpt-4o-mini"
    analysis_timeout_seconds: float = Field(default=30, gt=0, le=120)

    # Elice STT. The base URL identifies a private deployment, so it is read
    # from the environment like a credential and never committed.
    elice_api_key: SecretStr = SecretStr("")
    elice_stt_base_url: str = ""
    elice_stt_model: str = "whisper-large-v3"
    elice_stt_language: str = "korean"
    elice_stt_timeout_seconds: float = Field(default=60, gt=0, le=300)

    # Project LLM (Elice ML API, OpenAI-compatible). The base URL names a
    # private gateway, so it is read from the environment like a credential.
    llm_base_url: str = ""
    llm_api_key: SecretStr = SecretStr("")
    llm_model: str = "gpt-5.6-luna"
    llm_reasoning_effort: Literal["none", "low", "medium", "high"] | None = None
    llm_timeout_seconds: float = Field(default=60, gt=0, le=300)

    # Backend internal API (``/internal/v1``). The Agent posts suggestions here
    # and reads interview context back; transcripts go over the WebSocket
    # below. The URL names a private deployment, so it is read from the
    # environment like a credential.
    # How the Agent authenticates is not settled with Backend yet: an unset key
    # means no ``Authorization`` header at all, not an empty one.
    backend_base_url: str = ""
    backend_api_key: SecretStr = SecretStr("")
    backend_timeout_seconds: float = Field(default=10, gt=0, le=60)

    # Transcript WebSocket (``WS /internal/v1/sessions/{sessionId}/transcripts``).
    # The address is derived from ``backend_base_url`` rather than configured
    # separately - the contract puts it on the same host - so there is no second
    # private URL to keep out of the logs.
    #
    # All three numbers below are provisional. The contract's open item 3 is
    # "ACK 대기 시간·버퍼 상한·재연결 정책", which is not agreed with Backend yet;
    # these are defaults that keep a local run honest, not settled values, and
    # they are expected to change when that item closes.
    transcript_ack_timeout_seconds: float = Field(default=5, gt=0, le=120)
    transcript_max_pending: int = Field(default=200, gt=0, le=10_000)
    transcript_reconnect_backoff_seconds: float = Field(default=0.5, ge=0, le=30)

    @field_validator("llm_base_url")
    @classmethod
    def _base_url_ends_with_v1(cls, value: str) -> str:
        """The gateway serves the OpenAI routes under ``/v1``; add it if omitted."""

        value = value.strip().rstrip("/")
        if value and not value.endswith("/v1"):
            value += "/v1"
        return value

    @field_validator("llm_reasoning_effort", mode="before")
    @classmethod
    def _blank_effort_is_none(cls, value: object) -> object:
        """``LLM_REASONING_EFFORT=`` in .env means "do not send it"."""

        if isinstance(value, str) and not value.strip():
            return None
        return value

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    """Return one settings instance per process."""

    return Settings()
