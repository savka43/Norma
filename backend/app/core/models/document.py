from datetime import datetime
from uuid import UUID, uuid4

from pydantic import JsonValue
from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models.base import Base


class FormattingTemplate(Base):
    __tablename__ = "formatting_templates"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    supervisor_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )
    name: Mapped[str] = mapped_column(String(255))
    latest_version: Mapped[int] = mapped_column(default=1, server_default="1")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        CheckConstraint("length(btrim(name)) > 0 AND name = btrim(name)", name="name_trimmed"),
        CheckConstraint("latest_version > 0", name="version_positive"),
    )


class FormattingTemplateVersion(Base):
    __tablename__ = "formatting_template_versions"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    template_id: Mapped[UUID] = mapped_column(
        ForeignKey("formatting_templates.id", ondelete="RESTRICT")
    )
    number: Mapped[int]
    parameters: Mapped[dict[str, JsonValue]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("template_id", "number"),
        CheckConstraint("number > 0", name="number_positive"),
    )


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    thesis_id: Mapped[UUID] = mapped_column(
        ForeignKey("theses.id", ondelete="RESTRICT"), unique=True
    )
    content: Mapped[dict[str, JsonValue]] = mapped_column(JSONB)
    schema_version: Mapped[int] = mapped_column(default=1, server_default="1")
    revision: Mapped[int] = mapped_column(default=1, server_default="1")
    last_version_number: Mapped[int] = mapped_column(default=0, server_default="0")
    template_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("formatting_template_versions.id", ondelete="RESTRICT")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        CheckConstraint("revision > 0", name="revision_positive"),
        CheckConstraint("schema_version IN (1, 2, 3)", name="schema_supported"),
        CheckConstraint("last_version_number >= 0", name="version_number_nonnegative"),
    )


class DocumentEditLease(Base):
    __tablename__ = "document_edit_leases"

    document_id: Mapped[UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="RESTRICT"), primary_key=True
    )
    lease_id: Mapped[UUID] = mapped_column(default=uuid4, unique=True)
    holder_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    acquired_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    __table_args__ = (CheckConstraint("expires_at > acquired_at", name="positive_lifetime"),)


class DocumentVersion(Base):
    __tablename__ = "document_versions"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    document_id: Mapped[UUID] = mapped_column(ForeignKey("documents.id", ondelete="RESTRICT"))
    number: Mapped[int]
    document_revision: Mapped[int]
    content: Mapped[dict[str, JsonValue]] = mapped_column(JSONB)
    schema_version: Mapped[int]
    template_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("formatting_template_versions.id", ondelete="RESTRICT")
    )
    created_by_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    comment: Mapped[str | None] = mapped_column(String(2000))
    restored_from_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("document_versions.id", ondelete="RESTRICT")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("document_id", "number"),
        CheckConstraint("number > 0 AND document_revision > 0", name="numbers_positive"),
        CheckConstraint("schema_version IN (1, 2, 3)", name="schema_supported"),
    )
