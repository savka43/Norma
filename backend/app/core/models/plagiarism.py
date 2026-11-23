from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import JsonValue
from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models.base import Base


class CheckStatus(StrEnum):
    QUEUED = "queued"
    UPLOADING = "uploading"
    UPLOADED = "uploaded"
    STARTING = "starting"
    CHECKING = "checking"
    COMPLETED = "completed"
    FAILED = "failed"


ACTIVE_CHECK_SQL = "status NOT IN ('completed', 'failed')"


class PlagiarismCheck(Base):
    __tablename__ = "plagiarism_checks"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    version_id: Mapped[UUID] = mapped_column(
        ForeignKey("document_versions.id", ondelete="RESTRICT")
    )
    requested_by_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    status: Mapped[str] = mapped_column(String(12), default=CheckStatus.QUEUED)
    external_id: Mapped[int | None]
    result: Mapped[dict[str, JsonValue] | None] = mapped_column(JSONB(none_as_null=True))
    error_code: Mapped[str | None] = mapped_column(String(40))
    error_detail: Mapped[str | None] = mapped_column(String(1000))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_run_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    deadline_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    claim_id: Mapped[UUID | None]
    claim_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'uploading', 'uploaded', 'starting', "
            "'checking', 'completed', 'failed')",
            name="status_allowed",
        ),
        CheckConstraint(
            "status NOT IN ('uploaded', 'starting', 'checking', 'completed') "
            "OR (external_id IS NOT NULL AND external_id > 0)",
            name="external_id_required",
        ),
        CheckConstraint("(status = 'completed') = (result IS NOT NULL)", name="result_matches"),
        CheckConstraint("(status = 'failed') = (error_code IS NOT NULL)", name="error_matches"),
        CheckConstraint(
            "(status IN ('completed', 'failed')) = (finished_at IS NOT NULL)",
            name="finished_matches",
        ),
        CheckConstraint("(claim_id IS NULL) = (claim_until IS NULL)", name="claim_pair"),
        Index("ix_plagiarism_checks_version_created", "version_id", "created_at", "id"),
        Index(
            "uq_plagiarism_checks_active_version",
            "version_id",
            unique=True,
            postgresql_where=text(ACTIVE_CHECK_SQL),
        ),
        Index(
            "ix_plagiarism_checks_due",
            "next_run_at",
            "id",
            postgresql_where=text(ACTIVE_CHECK_SQL),
        ),
    )
