import os
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.core.config import Settings, load_settings
from app.main import create_app


@pytest.fixture
def settings() -> Settings:
    return Settings.model_validate(
        {
            "_env_file": None,
            "database_host": "127.0.0.1",
            "database_port": 1,
            "database_name": "norma_test",
            "database_user": "test",
            "database_password": SecretStr("unit-test-password"),
            "readiness_timeout_seconds": 0.05,
        }
    )


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    with TestClient(create_app(settings)) as test_client:
        yield test_client


@pytest.fixture(scope="session")
def integration_settings() -> Settings:
    if os.environ.get("NORMA_RUN_DB_TESTS") != "1":
        pytest.skip("Set NORMA_RUN_DB_TESTS=1 with a dedicated PostgreSQL test database")
    configuration = load_settings()
    if not configuration.database_name.endswith("_test"):
        pytest.fail("Database integration tests require a database name ending in _test")
    return configuration
