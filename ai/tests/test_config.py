from irya_ai.config import Settings


def test_settings_have_safe_local_defaults() -> None:
    settings = Settings(_env_file=None)

    assert settings.app_env == "local"
    assert settings.log_level == "INFO"
    assert settings.livekit_url == "ws://localhost:7880"
    assert settings.livekit_api_key.get_secret_value() == ""
    assert settings.livekit_api_secret.get_secret_value() == ""


def test_settings_load_environment_variables(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("LIVEKIT_URL", "ws://livekit.example.test")
    monkeypatch.setenv("LIVEKIT_API_KEY", "test-key")
    monkeypatch.setenv("LIVEKIT_API_SECRET", "test-secret")

    settings = Settings(_env_file=None)

    assert settings.app_env == "test"
    assert settings.log_level == "DEBUG"
    assert settings.livekit_url == "ws://livekit.example.test"
    assert settings.livekit_api_key.get_secret_value() == "test-key"
    assert settings.livekit_api_secret.get_secret_value() == "test-secret"


def test_secret_values_are_masked() -> None:
    settings = Settings(
        _env_file=None,
        livekit_api_key="visible-key",
        livekit_api_secret="visible-secret",
    )

    representation = repr(settings)

    assert "visible-key" not in representation
    assert "visible-secret" not in representation
