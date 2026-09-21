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

    # Cartesia streaming STT. Only the key is secret here: the endpoint is the
    # provider's own public host, not a deployment of ours, which is why
    # ``irya_ai.stt.cartesia`` has no ``protect_host`` call the way the Elice
    # client does. ``ink-whisper`` is not a default to change casually - the
    # plugin picks the mode from the model name, and ``ink-2`` transcribes
    # Korean into English syllables. See the module docstring.
    cartesia_api_key: SecretStr = SecretStr("")
    cartesia_stt_model: str = "ink-whisper"
    cartesia_stt_language: str = "ko"

    # Project LLM (Elice ML API, OpenAI-compatible). The base URL names a
    # private gateway, so it is read from the environment like a credential.
    llm_base_url: str = ""
    llm_api_key: SecretStr = SecretStr("")
    llm_model: str = "gpt-5.6-luna"
    llm_reasoning_effort: Literal["none", "low", "medium", "high"] | None = None
    llm_timeout_seconds: float = Field(default=60, gt=0, le=300)

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
