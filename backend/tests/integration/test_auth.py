from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api_v1.auth.dependencies import SupervisorDep
from app.api_v1.auth.schemas import SupervisorBootstrap
from app.api_v1.auth.service import EmailAlreadyExistsError, bootstrap_supervisor
from app.api_v1.dependencies import get_settings
from app.core.config import Settings
from app.core.models import AuthSession, User, UserRole
from app.core.security import SESSION_COOKIE_NAME, session_token_hash, verify_password

pytestmark = pytest.mark.integration

PASSWORD = "Synthetic-password-123"
REGISTRATION: dict[str, str] = {
    "email": "student@example.com",
    "full_name": "Тестовый Студент",
    "academic_group": "ИДБ-23-08",
    "password": PASSWORD,
}
CREDENTIALS = {"email": REGISTRATION["email"], "password": PASSWORD}


async def register_and_login(client: AsyncClient) -> str:
    assert (await client.post("/api/v1/auth/register", json=REGISTRATION)).status_code == 201
    response = await client.post("/api/v1/auth/login", json=CREDENTIALS)
    assert response.status_code == 200
    return response.cookies[SESSION_COOKIE_NAME]


async def test_student_registration_stores_hash_and_returns_public_profile(
    api_client: AsyncClient, db_session: AsyncSession
) -> None:
    response = await api_client.post(
        "/api/v1/auth/register",
        json={
            **REGISTRATION,
            "full_name": "  Тестовый Студент  ",
            "academic_group": "  ИДБ-23-08  ",
        },
    )
    assert response.status_code == 201
    result = response.json()
    assert result["role"] == "student"
    assert result["full_name"] == REGISTRATION["full_name"]
    assert result["academic_group"] == REGISTRATION["academic_group"]
    assert result["department"] is None and result["position"] is None
    assert "password" not in response.text and PASSWORD not in response.text
    assert not response.cookies
    user = await db_session.scalar(select(User))
    assert user is not None and str(user.id) == result["id"]
    assert user.password_hash.startswith("$argon2id$")
    assert verify_password(PASSWORD, user.password_hash)[0]
    assert (await api_client.get("/api/v1/auth/me")).status_code == 401


@pytest.mark.parametrize(
    "changes",
    [
        {"role": "supervisor"},
        {"position": "Доцент"},
        {"password_hash": "injected"},
        {"email": "invalid-email"},
        {"full_name": " \t\n "},
        {"academic_group": " \t "},
        {"password": "P@ss-123"},
        {"password": "p" * 129},
    ],
)
async def test_invalid_registration_never_persists_or_echoes_password(
    api_client: AsyncClient, db_session: AsyncSession, changes: dict[str, str]
) -> None:
    data = {**REGISTRATION, **changes}
    response = await api_client.post("/api/v1/auth/register", json=data)
    assert response.status_code == 422
    assert data["password"] not in response.text
    assert all("input" not in error for error in response.json()["detail"])
    assert await db_session.scalar(select(func.count()).select_from(User)) == 0


async def test_duplicate_email_is_case_insensitive_and_leaves_session_usable(
    api_client: AsyncClient, db_session: AsyncSession
) -> None:
    await register_and_login(api_client)
    response = await api_client.post(
        "/api/v1/auth/register", json={**REGISTRATION, "email": "STUDENT@EXAMPLE.COM"}
    )
    assert response.status_code == 409
    assert await db_session.scalar(select(func.count()).select_from(User)) == 1
    assert (await api_client.get("/api/v1/auth/me")).status_code == 200


async def test_unicode_email_lookup_uses_same_database_rules_as_unique_index(
    api_client: AsyncClient,
) -> None:
    # Python and PostgreSQL may lowercase dotted capital I differently.
    email = "İstanbul@example.com"
    registration = await api_client.post(
        "/api/v1/auth/register", json={**REGISTRATION, "email": email}
    )
    assert registration.status_code == 201
    response = await api_client.post("/api/v1/auth/login", json={**CREDENTIALS, "email": email})
    assert response.status_code == 200
    assert response.json()["id"] == registration.json()["id"]


async def test_login_me_and_logout_revoke_token_in_database(
    api_client: AsyncClient, db_session: AsyncSession
) -> None:
    await api_client.post("/api/v1/auth/register", json=REGISTRATION)
    response = await api_client.post(
        "/api/v1/auth/login", json={**CREDENTIALS, "email": "STUDENT@EXAMPLE.COM"}
    )
    assert response.status_code == 200
    token = response.cookies[SESSION_COOKIE_NAME]
    cookie = response.headers["set-cookie"]
    assert "HttpOnly" in cookie and "SameSite=lax" in cookie and "Path=/api/v1" in cookie
    assert "Max-Age=28800" in cookie
    assert response.headers["cache-control"] == "no-store"
    stored = await db_session.scalar(select(AuthSession))
    assert stored is not None and stored.token_hash == session_token_hash(token)
    assert stored.token_hash != token
    assert int((stored.expires_at - stored.created_at).total_seconds()) == 28800
    me = await api_client.get("/api/v1/auth/me")
    assert me.status_code == 200 and me.json() == response.json()
    assert me.headers["cache-control"] == "no-store"
    assert PASSWORD not in me.text and "password_hash" not in me.text
    logout = await api_client.post("/api/v1/auth/logout")
    assert logout.status_code == 204 and logout.content == b""
    assert "Max-Age=0" in logout.headers["set-cookie"]
    assert await db_session.scalar(select(func.count()).select_from(AuthSession)) == 0
    # Replay the original token after server-side revocation.
    api_client.cookies.set(SESSION_COOKIE_NAME, token, domain="testserver.local", path="/api/v1")
    assert (await api_client.get("/api/v1/auth/me")).status_code == 401
    assert (await api_client.post("/api/v1/auth/logout")).status_code == 204


@pytest.mark.parametrize(
    "credentials",
    [
        {**CREDENTIALS, "password": "wrong-password"},
        {**CREDENTIALS, "email": "missing@example.com"},
    ],
)
async def test_login_errors_do_not_reveal_account_existence(
    api_client: AsyncClient, db_session: AsyncSession, credentials: dict[str, str]
) -> None:
    await api_client.post("/api/v1/auth/register", json=REGISTRATION)
    response = await api_client.post("/api/v1/auth/login", json=credentials)
    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid email or password"}
    assert not response.cookies
    assert await db_session.scalar(select(func.count()).select_from(AuthSession)) == 0


async def test_relogin_rotates_token_and_failure_does_not_destroy_session(
    api_client: AsyncClient, db_session: AsyncSession
) -> None:
    first = await register_and_login(api_client)
    assert (
        await api_client.post(
            "/api/v1/auth/login", json={**CREDENTIALS, "password": "wrong-password"}
        )
    ).status_code == 401
    assert (await api_client.get("/api/v1/auth/me")).status_code == 200
    second = await api_client.post("/api/v1/auth/login", json=CREDENTIALS)
    assert second.cookies[SESSION_COOKIE_NAME] != first
    assert await db_session.get(AuthSession, session_token_hash(first)) is None
    assert await db_session.scalar(select(func.count()).select_from(AuthSession)) == 1


@pytest.mark.parametrize("token", ["junk", "A" * 43, "a" * 5000])
async def test_unrecognized_token_does_not_authenticate(
    api_client: AsyncClient, token: str
) -> None:
    api_client.cookies.set(SESSION_COOKIE_NAME, token)
    assert (await api_client.get("/api/v1/auth/me")).status_code == 401


async def test_expired_session_is_rejected_by_server(
    api_client: AsyncClient, db_session: AsyncSession
) -> None:
    await register_and_login(api_client)
    now = datetime.now(UTC)
    await db_session.execute(
        update(AuthSession).values(
            created_at=now - timedelta(hours=1), expires_at=now - timedelta(seconds=1)
        )
    )
    await db_session.commit()
    assert (await api_client.get("/api/v1/auth/me")).status_code == 401


async def test_independent_clients_have_independent_sessions(
    api_client: AsyncClient, api_app: FastAPI, db_session: AsyncSession
) -> None:
    token = await register_and_login(api_client)
    async with AsyncClient(
        transport=ASGITransport(app=api_app),
        base_url="http://testserver",
        headers={"X-CSRF-Protection": "1"},
    ) as second_client:
        assert (await second_client.get("/api/v1/auth/me")).status_code == 401
        response = await second_client.post("/api/v1/auth/login", json=CREDENTIALS)
        assert response.cookies[SESSION_COOKIE_NAME] != token
        assert await db_session.scalar(select(func.count()).select_from(AuthSession)) == 2
        await second_client.post("/api/v1/auth/logout")
        assert (await api_client.get("/api/v1/auth/me")).status_code == 200


async def test_deleted_user_cannot_use_session(
    api_client: AsyncClient, db_session: AsyncSession
) -> None:
    await register_and_login(api_client)
    await db_session.execute(delete(User))
    await db_session.commit()
    assert (await api_client.get("/api/v1/auth/me")).status_code == 401
    assert await db_session.scalar(select(func.count()).select_from(AuthSession)) == 0


async def test_bootstrap_supervisor_and_role_dependency(
    api_client: AsyncClient, api_app: FastAPI, db_session: AsyncSession
) -> None:
    @api_app.get("/api/v1/test/supervisor")
    async def supervisor_only(user: SupervisorDep) -> str:
        return str(user.id)

    assert (await api_client.get("/api/v1/test/supervisor")).status_code == 401
    await register_and_login(api_client)
    assert (await api_client.get("/api/v1/test/supervisor")).status_code == 403
    data = SupervisorBootstrap.model_validate(
        {
            "email": "supervisor@example.com",
            "full_name": "Тестовый Руководитель",
            "position": "Доцент",
            "department": "Информационные системы",
            "password": PASSWORD,
        }
    )
    user = await bootstrap_supervisor(db_session, data)
    assert user.role is UserRole.SUPERVISOR and user.academic_group is None
    assert user.position == data.position and user.department == data.department
    assert verify_password(PASSWORD, user.password_hash)[0]
    response = await api_client.post(
        "/api/v1/auth/login", json={"email": data.email, "password": PASSWORD}
    )
    assert response.status_code == 200 and response.json()["role"] == "supervisor"
    assert (await api_client.get("/api/v1/test/supervisor")).status_code == 200
    with pytest.raises(EmailAlreadyExistsError):
        await bootstrap_supervisor(db_session, data)
    # Bootstrap must never overwrite or elevate an existing student.
    with pytest.raises(EmailAlreadyExistsError):
        await bootstrap_supervisor(
            db_session, data.model_copy(update={"email": REGISTRATION["email"]})
        )
    student = await db_session.scalar(select(User).where(User.role == UserRole.STUDENT))
    assert student is not None and student.password_hash.startswith("$argon2id$")


async def test_cookie_security_and_lifetime_are_configurable(
    api_client: AsyncClient, api_app: FastAPI, integration_settings: Settings
) -> None:
    settings = integration_settings.model_copy(
        update={"session_cookie_secure": True, "session_lifetime_seconds": 60}
    )
    api_app.dependency_overrides[get_settings] = lambda: settings
    await api_client.post("/api/v1/auth/register", json=REGISTRATION)
    response = await api_client.post("/api/v1/auth/login", json=CREDENTIALS)
    assert response.status_code == 200
    assert "Secure" in response.headers["set-cookie"]
    assert "Max-Age=60" in response.headers["set-cookie"]
    assert (await api_client.get("/api/v1/auth/me")).status_code == 401
    assert (await api_client.get("https://testserver/api/v1/auth/me")).status_code == 200
