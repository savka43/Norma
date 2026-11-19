from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL

PROJECT_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="NORMA_",
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        hide_input_in_errors=True,
    )

    database_host: str = Field(default="127.0.0.1", min_length=1)
    database_port: int = Field(default=5432, ge=1, le=65535)
    database_name: str = Field(default="norma", min_length=1)
    database_user: str = Field(default="norma", min_length=1)
    database_password: SecretStr = Field(min_length=1)
    database_connect_timeout_seconds: float = Field(default=5, gt=0, le=60)
    readiness_timeout_seconds: float = Field(default=3, gt=0, le=60)
    session_lifetime_seconds: int = Field(default=28800, ge=60, le=2592000)
    session_cookie_secure: bool = False

    @property
    def database_url(self) -> URL:
        return URL.create(
            drivername="postgresql+asyncpg",
            username=self.database_user,
            password=self.database_password.get_secret_value(),
            host=self.database_host,
            port=self.database_port,
            database=self.database_name,
        )


def load_settings() -> Settings:
    """Validate configuration populated by the environment and dotenv sources."""
    return Settings.model_validate({})
