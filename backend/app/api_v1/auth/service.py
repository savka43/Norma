from datetime import UTC, datetime, timedelta

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.api_v1.auth import crud
from app.api_v1.auth.schemas import StudentRegistration, SupervisorBootstrap
from app.core.config import Settings
from app.core.models import AuthSession, User, UserRole
from app.core.security import (
    hash_password,
    new_session_token,
    session_token_hash,
    verify_password,
)


class EmailAlreadyExistsError(Exception):
    pass


async def _save_user(session: AsyncSession, user: User) -> User:
    session.add(user)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        cause = getattr(exc.orig, "__cause__", None)
        if getattr(cause, "constraint_name", None) == "ix_users_email_lower":
            raise EmailAlreadyExistsError from exc
        raise
    return user


async def register_student(session: AsyncSession, data: StudentRegistration) -> User:
    password_hash = await run_in_threadpool(hash_password, data.password.get_secret_value())
    return await _save_user(
        session,
        User(
            email=str(data.email),
            password_hash=password_hash,
            full_name=data.full_name,
            academic_group=data.academic_group,
            role=UserRole.STUDENT,
        ),
    )


async def bootstrap_supervisor(session: AsyncSession, data: SupervisorBootstrap) -> User:
    password_hash = await run_in_threadpool(hash_password, data.password.get_secret_value())
    return await _save_user(
        session,
        User(
            email=str(data.email),
            password_hash=password_hash,
            full_name=data.full_name,
            position=data.position,
            department=data.department,
            role=UserRole.SUPERVISOR,
        ),
    )


async def login(
    session: AsyncSession,
    settings: Settings,
    email: str,
    password: str,
    previous_token: str | None,
) -> tuple[User, str] | None:
    user = await crud.find_user_by_email(session, email)
    valid, replacement_hash = await run_in_threadpool(
        verify_password, password, user.password_hash if user is not None else None
    )
    if not valid or user is None:
        return None
    if replacement_hash is not None:
        user.password_hash = replacement_hash
    previous_hash = session_token_hash(previous_token)
    if previous_hash is not None:
        await crud.delete_session(session, previous_hash)
    token = new_session_token()
    token_hash = session_token_hash(token)
    assert token_hash is not None
    now = datetime.now(UTC)
    session.add(
        AuthSession(
            token_hash=token_hash,
            user_id=user.id,
            created_at=now,
            expires_at=now + timedelta(seconds=settings.session_lifetime_seconds),
        )
    )
    await session.commit()
    return user, token


async def logout(session: AsyncSession, token: str | None) -> None:
    token_hash = session_token_hash(token)
    if token_hash is not None:
        await crud.delete_session(session, token_hash)
        await session.commit()
