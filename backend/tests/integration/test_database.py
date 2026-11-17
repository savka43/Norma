import asyncio
import os
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import text

from app.core.config import Settings
from app.core.database import create_engine
from app.main import create_app

pytestmark = pytest.mark.integration
BACKEND_ROOT = Path(__file__).resolve().parents[2]


def test_readiness_with_real_postgresql(integration_settings: Settings) -> None:
    with TestClient(create_app(integration_settings)) as client:
        response = client.get("/api/v1/health/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}


def test_readiness_with_invalid_database_credentials(integration_settings: Settings) -> None:
    invalid_settings = integration_settings.model_copy(
        update={"database_password": SecretStr("invalid-test-password")}
    )
    with TestClient(create_app(invalid_settings)) as client:
        response = client.get("/api/v1/health/ready")
    assert response.status_code == 503
    assert response.json() == {"detail": "Database is unavailable"}


def test_migration_round_trip(integration_settings: Settings) -> None:
    environment = dict(os.environ)
    environment.update(
        NORMA_DATABASE_HOST=integration_settings.database_host,
        NORMA_DATABASE_PORT=str(integration_settings.database_port),
        NORMA_DATABASE_NAME=integration_settings.database_name,
        NORMA_DATABASE_USER=integration_settings.database_user,
        NORMA_DATABASE_PASSWORD=integration_settings.database_password.get_secret_value(),
    )

    def alembic(*arguments: str) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "alembic", *arguments],
            cwd=BACKEND_ROOT,
            env=environment,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        assert result.returncode == 0, result.stdout + result.stderr

    async def current_revision() -> str | None:
        engine = create_engine(integration_settings)
        try:
            async with engine.connect() as connection:
                return await connection.scalar(text("SELECT version_num FROM alembic_version"))
        finally:
            await engine.dispose()

    alembic("upgrade", "head")
    assert asyncio.run(current_revision()) == "0001_api_foundation"
    alembic("check")
    alembic("downgrade", "base")
    assert asyncio.run(current_revision()) is None
    alembic("upgrade", "head")
