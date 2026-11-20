from datetime import date, datetime
from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, Enum, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models.base import Base


class StageStatus(StrEnum):
    IN_PROGRESS = "in_progress"
    IN_REVIEW = "in_review"
    CHANGES_REQUESTED = "changes_requested"
    COMPLETED = "completed"


def _status_values(statuses: type[StageStatus]) -> list[str]:
    return [status.value for status in statuses]


class Thesis(Base):
    __tablename__ = "theses"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    student_id: Mapped[UUID] = mapped_column(
        ForeignKey("group_memberships.student_id", ondelete="RESTRICT"), unique=True
    )
    supervisor_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )
    title: Mapped[str] = mapped_column(String(500))
    start_date: Mapped[date]
    due_date: Mapped[date]
    revision: Mapped[int] = mapped_column(default=1, server_default="1")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        CheckConstraint("length(btrim(title)) > 0 AND title = btrim(title)", name="title_trimmed"),
        CheckConstraint("due_date >= start_date", name="date_order"),
        CheckConstraint("revision > 0", name="revision_positive"),
    )


class ThesisStage(Base):
    __tablename__ = "thesis_stages"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    thesis_id: Mapped[UUID] = mapped_column(ForeignKey("theses.id", ondelete="RESTRICT"))
    name: Mapped[str] = mapped_column(String(255))
    position: Mapped[int]
    due_date: Mapped[date]
    status: Mapped[StageStatus] = mapped_column(
        Enum(
            StageStatus, name="stage_status", values_callable=_status_values, validate_strings=True
        ),
        default=StageStatus.IN_PROGRESS,
        server_default=StageStatus.IN_PROGRESS.value,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("thesis_id", "position", deferrable=True, initially="DEFERRED"),
        CheckConstraint("position > 0", name="position_positive"),
        CheckConstraint("length(btrim(name)) > 0 AND name = btrim(name)", name="name_trimmed"),
    )


class StageEvent(Base):
    __tablename__ = "stage_events"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    stage_id: Mapped[UUID] = mapped_column(
        ForeignKey("thesis_stages.id", ondelete="RESTRICT"), index=True
    )
    actor_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    thesis_revision: Mapped[int]
    kind: Mapped[str] = mapped_column(String(20))
    before: Mapped[dict[str, str | int] | None] = mapped_column(
        JSONB(none_as_null=True), nullable=True
    )
    after: Mapped[dict[str, str | int]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("stage_id", "thesis_revision"),
        CheckConstraint("thesis_revision > 0", name="revision_positive"),
        CheckConstraint("kind IN ('created', 'updated')", name="kind_allowed"),
        CheckConstraint(
            "(kind = 'created' AND before IS NULL) OR (kind = 'updated' AND before IS NOT NULL)",
            name="before_matches_kind",
        ),
    )
