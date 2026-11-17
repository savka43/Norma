import asyncio
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from app.api_v1.health import views


def test_liveness_does_not_require_database(client: TestClient) -> None:
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readiness_when_database_responds(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    probe = AsyncMock()
    monkeypatch.setattr(views, "check_database", probe)
    response = client.get("/api/v1/health/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}
    probe.assert_awaited_once()


@pytest.mark.parametrize(
    "error",
    [
        OperationalError("SELECT 1", {}, Exception("sensitive connection details")),
        OSError("sensitive connection details"),
        TimeoutError("sensitive connection details"),
    ],
)
def test_readiness_hides_connection_errors(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, error: Exception
) -> None:
    monkeypatch.setattr(views, "check_database", AsyncMock(side_effect=error))
    response = client.get("/api/v1/health/ready")
    assert response.status_code == 503
    assert response.json() == {"detail": "Database is unavailable"}
    assert "sensitive" not in response.text
    assert client.get("/api/v1/health").status_code == 200


def test_readiness_has_bounded_wait(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    async def slow_probe(_session: object) -> None:
        await asyncio.sleep(1)

    monkeypatch.setattr(views, "check_database", slow_probe)
    response = client.get("/api/v1/health/ready")
    assert response.status_code == 503


def test_openapi_describes_health_endpoints(client: TestClient) -> None:
    response = client.get("/openapi.json")
    assert response.status_code == 200
    paths = response.json()["paths"]
    assert "/api/v1/health" in paths
    assert "503" in paths["/api/v1/health/ready"]["get"]["responses"]
