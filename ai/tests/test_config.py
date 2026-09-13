from irya_ai.config import Settings


def test_settings_have_safe_local_defaults() -> None:
    settings = Settings(_env_file=None)

    assert settings.app_env == "local"
    assert settings.log_level == "INFO"
    assert settings.livekit_url == "ws://localhost:7880"
    assert settings.livekit_api_key.get_secret_value() == ""
    assert settings.livekit_api_secret.get_secret_value() == ""
    assert settings.openai_model == "gpt-4o-mini"
    assert settings.openai_api_key.get_secret_value() == ""
    assert settings.elice_api_key.get_secret_value() == ""
    # The deployment host is private, so there is no default to fall back to.
    assert settings.elice_stt_base_url == ""
    assert settings.elice_stt_model == "whisper-large-v3"
    assert settings.elice_stt_language == "korean"
    assert settings.elice_stt_timeout_seconds == 60


def test_settings_load_environment_variables(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("LIVEKIT_URL", "ws://livekit.example.test")
    monkeypatch.setenv("LIVEKIT_API_KEY", "test-key")
    monkeypatch.setenv("LIVEKIT_API_SECRET", "test-secret")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-4o")
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    monkeypatch.setenv("ELICE_API_KEY", "test-elice-key")
    monkeypatch.setenv("ELICE_STT_BASE_URL", "https://stt.example.test")
    monkeypatch.setenv("ELICE_STT_MODEL", "whisper-large-v3-turbo")
    monkeypatch.setenv("ELICE_STT_LANGUAGE", "english")
    monkeypatch.setenv("ELICE_STT_TIMEOUT_SECONDS", "15")

    settings = Settings(_env_file=None)

    assert settings.app_env == "test"
    assert settings.log_level == "DEBUG"
    assert settings.livekit_url == "ws://livekit.example.test"
    assert settings.livekit_api_key.get_secret_value() == "test-key"
    assert settings.livekit_api_secret.get_secret_value() == "test-secret"
    assert settings.openai_model == "gpt-4o"
    assert settings.openai_api_key.get_secret_value() == "test-openai-key"
    assert settings.elice_api_key.get_secret_value() == "test-elice-key"
    assert settings.elice_stt_base_url == "https://stt.example.test"
    assert settings.elice_stt_model == "whisper-large-v3-turbo"
    assert settings.elice_stt_language == "english"
    assert settings.elice_stt_timeout_seconds == 15


def test_secret_values_are_masked() -> None:
    settings = Settings(
        _env_file=None,
        livekit_api_key="visible-key",
        livekit_api_secret="visible-secret",
        openai_api_key="visible-openai-key",
        elice_api_key="visible-elice-key",
    )

    representation = repr(settings)

    assert "visible-key" not in representation
    assert "visible-secret" not in representation
    assert "visible-openai-key" not in representation
    assert "visible-elice-key" not in representation
