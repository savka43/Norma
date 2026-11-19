import pytest
from fastapi.testclient import TestClient

from app.core.security import hash_password, session_token_hash, verify_password


def test_password_hash_is_salted_and_does_not_normalize_password() -> None:
    password = "  Проверочный пароль  "
    first = hash_password(password)
    assert first.startswith("$argon2id$")
    assert password not in first
    assert first != hash_password(password)
    assert verify_password(password, first) == (True, None)
    assert verify_password(password.strip(), first) == (False, None)
    assert verify_password("not-a-user-password", None)[0] is False


@pytest.mark.parametrize("token", [None, "", "short", "a" * 10000, "я" * 43, "!" * 43])
def test_invalid_session_tokens_are_rejected(token: str | None) -> None:
    assert session_token_hash(token) is None


@pytest.mark.parametrize("path", ["register", "login", "logout"])
def test_auth_mutations_require_custom_header(client: TestClient, path: str) -> None:
    response = client.post(f"/api/v1/auth/{path}", json={})
    assert response.status_code == 403
    response = client.post(f"/api/v1/auth/{path}", json={}, headers={"X-CSRF-Protection": "wrong"})
    assert response.status_code == 403


def test_cross_origin_preflight_is_not_allowed(client: TestClient) -> None:
    response = client.options(
        "/api/v1/auth/logout",
        headers={
            "Origin": "https://untrusted.example",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "X-CSRF-Protection",
        },
    )
    assert "access-control-allow-origin" not in response.headers


def test_openapi_describes_cookie_auth_and_password_input(client: TestClient) -> None:
    schema = client.get("/openapi.json").json()
    assert schema["components"]["securitySchemes"]["APIKeyCookie"] == {
        "type": "apiKey",
        "in": "cookie",
        "name": "norma_session",
    }
    assert schema["paths"]["/api/v1/auth/me"]["get"]["security"] == [{"APIKeyCookie": []}]
    fields = schema["components"]["schemas"]["UserResponse"]["properties"]
    assert "password" not in fields and "password_hash" not in fields
