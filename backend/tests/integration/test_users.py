from uuid import UUID

import pytest
from sqlalchemy import text, update
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.models import User, UserRole

pytestmark = pytest.mark.integration

# A synthetic value: these tests exercise storage, not password hashing or authentication.
PASSWORD_HASH = "synthetic-password-hash"


def make_user(role: UserRole = UserRole.STUDENT, email: str = "student@example.test") -> User:
    return User(
        email=email,
        full_name="Тестовый Студент" if role == UserRole.STUDENT else "Тестовый Руководитель",
        password_hash=PASSWORD_HASH,
        role=role,
        academic_group="ИДБ-23-08" if role == UserRole.STUDENT else None,
        position="Доцент" if role == UserRole.SUPERVISOR else None,
        department="Информационные системы" if role == UserRole.SUPERVISOR else None,
    )


@pytest.mark.parametrize("role", [UserRole.STUDENT, UserRole.SUPERVISOR])
async def test_user_persists_with_role_and_profile(
    db_session: AsyncSession, role: UserRole
) -> None:
    user = make_user(role)
    db_session.add(user)
    await db_session.commit()
    user_id = user.id
    assert isinstance(user_id, UUID)
    assert user_id.version == 4
    assert user.created_at.utcoffset() is not None

    db_session.expunge_all()
    stored = await db_session.get(User, user_id)
    assert stored is not None
    assert stored.role is role
    assert stored.password_hash == PASSWORD_HASH
    if role == UserRole.STUDENT:
        assert stored.academic_group == "ИДБ-23-08"
        assert stored.position is None and stored.department is None
    else:
        assert stored.position == "Доцент"
        assert stored.department == "Информационные системы"
        assert stored.academic_group is None


@pytest.mark.parametrize("duplicate_email", ["student@example.test", "STUDENT@Example.Test"])
async def test_email_is_unique_across_roles_ignoring_case(
    db_session: AsyncSession, duplicate_email: str
) -> None:
    db_session.add(make_user())
    await db_session.commit()
    db_session.add(make_user(UserRole.SUPERVISOR, duplicate_email))
    with pytest.raises(IntegrityError, match="ix_users_email_lower"):
        await db_session.flush()
    await db_session.rollback()


async def test_email_uniqueness_also_applies_to_updates(db_session: AsyncSession) -> None:
    student = make_user()
    supervisor = make_user(UserRole.SUPERVISOR, "supervisor@example.test")
    db_session.add_all([student, supervisor])
    await db_session.commit()
    with pytest.raises(IntegrityError, match="ix_users_email_lower"):
        await db_session.execute(
            update(User).where(User.id == supervisor.id).values(email="STUDENT@EXAMPLE.TEST")
        )
    await db_session.rollback()


@pytest.mark.parametrize("role", ["admin", "STUDENT", ""])
async def test_database_rejects_unknown_roles(db_session: AsyncSession, role: str) -> None:
    user = make_user()
    db_session.add(user)
    await db_session.commit()
    with pytest.raises(DBAPIError, match="invalid input value for enum user_role"):
        await db_session.execute(
            text("UPDATE users SET role = :role WHERE id = :id"), {"role": role, "id": user.id}
        )
    await db_session.rollback()


@pytest.mark.parametrize("field", ["email", "full_name", "password_hash", "role", "created_at"])
async def test_database_rejects_null_account_fields(db_session: AsyncSession, field: str) -> None:
    user = make_user()
    db_session.add(user)
    await db_session.commit()
    with pytest.raises(IntegrityError, match="not-null constraint"):
        await db_session.execute(update(User).where(User.id == user.id).values({field: None}))
    await db_session.rollback()


@pytest.mark.parametrize(
    ("field", "value", "constraint"),
    [
        ("email", "", "ck_users_email_trimmed"),
        ("email", " student@example.test ", "ck_users_email_trimmed"),
        ("full_name", "   ", "ck_users_full_name_not_blank"),
        ("password_hash", "   ", "ck_users_password_hash_not_blank"),
    ],
)
async def test_database_rejects_blank_or_padded_account_fields(
    db_session: AsyncSession, field: str, value: str, constraint: str
) -> None:
    user = make_user()
    db_session.add(user)
    await db_session.commit()
    with pytest.raises(IntegrityError, match=constraint):
        await db_session.execute(update(User).where(User.id == user.id).values({field: value}))
    await db_session.rollback()


@pytest.mark.parametrize(
    ("role", "changes"),
    [
        (UserRole.STUDENT, {"academic_group": None}),
        (UserRole.STUDENT, {"academic_group": "   "}),
        (UserRole.STUDENT, {"position": "Доцент"}),
        (UserRole.STUDENT, {"department": "Кафедра"}),
        (UserRole.SUPERVISOR, {"academic_group": "ИДБ-23-08"}),
        (UserRole.SUPERVISOR, {"position": None}),
        (UserRole.SUPERVISOR, {"position": "   "}),
        (UserRole.SUPERVISOR, {"department": None}),
        (UserRole.SUPERVISOR, {"department": "   "}),
        (UserRole.STUDENT, {"role": UserRole.SUPERVISOR}),
    ],
)
async def test_database_rejects_profile_inconsistent_with_role(
    db_session: AsyncSession, role: UserRole, changes: dict[str, str | None]
) -> None:
    user = make_user(role)
    db_session.add(user)
    await db_session.commit()
    with pytest.raises(IntegrityError, match="ck_users_role_profile"):
        await db_session.execute(update(User).where(User.id == user.id).values(changes))
    await db_session.rollback()
