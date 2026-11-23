from pathlib import Path

from pydantic import Field, HttpUrl, SecretStr, field_validator, model_validator
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
    document_lease_seconds: int = Field(default=120, ge=30, le=3600)
    pdf_converter: str = Field(default="libreoffice", min_length=1)
    pdf_timeout_seconds: int = Field(default=60, ge=1, le=120)
    plagiarism_enabled: bool = False
    plagiarism_wsdl_url: HttpUrl = HttpUrl("https://api.antiplagiat.ru:4959/apiCorp/testapi?wsdl")
    plagiarism_site_url: HttpUrl = HttpUrl("https://testapi.antiplagiat.ru")
    plagiarism_login: SecretStr = SecretStr("")
    plagiarism_password: SecretStr = SecretStr("")
    plagiarism_request_timeout_seconds: float = Field(default=30, gt=0, le=120)
    plagiarism_poll_seconds: int = Field(default=10, ge=1, le=300)
    plagiarism_check_timeout_seconds: int = Field(default=3600, ge=60, le=86400)
    plagiarism_max_text_bytes: int | None = Field(default=None, gt=0)

    @field_validator("plagiarism_max_text_bytes", mode="before")
    @classmethod
    def parse_optional_text_limit(cls, value: object) -> object:
        return None if value == "" else value

    @model_validator(mode="after")
    def validate_plagiarism_configuration(self) -> "Settings":
        for url in (self.plagiarism_wsdl_url, self.plagiarism_site_url):
            if url.scheme != "https" or url.username or url.password or url.fragment:
                raise ValueError("Antiplagiat URLs must use HTTPS without credentials or fragments")
        if self.plagiarism_wsdl_url.query not in {"wsdl", "singleWsdl"}:
            raise ValueError("Antiplagiat WSDL URL must end in ?wsdl or ?singleWsdl")
        if self.plagiarism_site_url.query or self.plagiarism_site_url.path not in {"", "/"}:
            raise ValueError("Antiplagiat site URL must be an origin")
        if self.plagiarism_enabled and not (
            self.plagiarism_login.get_secret_value().strip()
            and self.plagiarism_password.get_secret_value()
        ):
            raise ValueError("Antiplagiat credentials are required when enabled")
        return self

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
