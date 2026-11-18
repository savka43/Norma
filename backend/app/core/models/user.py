from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, Enum, Index, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models.base import Base


class UserRole(StrEnum):
    STUDENT = "student"
    SUPERVISOR = "supervisor"


def _role_values(roles: type[UserRole]) -> list[str]:
    return [role.value for role in roles]


class User(Base):
    __tablename__ = "users"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    email: Mapped[str] = mapped_column(String(254))
    full_name: Mapped[str] = mapped_column(String(255))
    password_hash: Mapped[str] = mapped_column(Text)
    role: Mapped[UserRole] = mapped_column(
        Enum(
            UserRole,
            name="user_role",
            values_callable=_role_values,
            validate_strings=True,
        )
    )
    academic_group: Mapped[str | None] = mapped_column(String(100))
    position: Mapped[str | None] = mapped_column(String(255))
    department: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_users_email_lower", func.lower(email), unique=True),
        CheckConstraint("length(btrim(email)) > 0 AND email = btrim(email)", name="email_trimmed"),
        CheckConstraint("length(btrim(full_name)) > 0", name="full_name_not_blank"),
        CheckConstraint("length(btrim(password_hash)) > 0", name="password_hash_not_blank"),
        CheckConstraint(
            "(role = 'student' AND academic_group IS NOT NULL "
            "AND length(btrim(academic_group)) > 0 AND position IS NULL AND department IS NULL) "
            "OR (role = 'supervisor' AND academic_group IS NULL AND position IS NOT NULL "
            "AND length(btrim(position)) > 0 AND department IS NOT NULL "
            "AND length(btrim(department)) > 0)",
            name="role_profile",
        ),
    )
