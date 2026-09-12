"""Application configuration loaded from environment variables."""

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
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

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    """Return one settings instance per process."""

    return Settings()
