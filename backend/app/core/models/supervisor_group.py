from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models.base import Base


class SupervisorGroup(Base):
    __tablename__ = "supervisor_groups"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    supervisor_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )
    name: Mapped[str] = mapped_column(String(255))
    academic_year: Mapped[int]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        CheckConstraint("length(btrim(name)) > 0 AND name = btrim(name)", name="name_trimmed"),
        CheckConstraint("academic_year BETWEEN 1 AND 9998", name="academic_year_range"),
    )


class GroupMembership(Base):
    __tablename__ = "group_memberships"

    # A student can belong to only one supervisor group, including across supervisors/years.
    student_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), primary_key=True
    )
    group_id: Mapped[UUID] = mapped_column(
        ForeignKey("supervisor_groups.id", ondelete="RESTRICT"), index=True
    )
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
