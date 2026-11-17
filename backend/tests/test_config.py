import pytest
from pydantic import SecretStr, ValidationError

from app.core.config import Settings


def test_database_password_is_redacted_and_preserves_special_characters() -> None:
    password = "local:@/%password"
    settings = Settings.model_validate(
        {"_env_file": None, "database_password": SecretStr(password)}
    )
    assert password not in repr(settings)
    assert password not in str(settings.database_url)
    assert settings.database_url.password == password


def test_settings_can_be_loaded_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NORMA_DATABASE_PASSWORD", "environment-password")
    monkeypatch.setenv("NORMA_DATABASE_PORT", "55432")
    settings = Settings.model_validate({"_env_file": None})
    assert settings.database_password.get_secret_value() == "environment-password"
    assert settings.database_port == 55432


def test_settings_reject_empty_password() -> None:
    with pytest.raises(ValidationError):
        Settings.model_validate({"_env_file": None, "database_password": SecretStr("")})
