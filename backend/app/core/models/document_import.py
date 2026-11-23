from datetime import datetime
from uuid import UUID, uuid4

from pydantic import JsonValue
from sqlalchemy import CheckConstraint, DateTime, ForeignKey, LargeBinary, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models.base import Base


class DocumentImport(Base):
    __tablename__ = "document_imports"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    document_id: Mapped[UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="RESTRICT"), index=True
    )
    version_id: Mapped[UUID] = mapped_column(
        ForeignKey("document_versions.id", ondelete="RESTRICT"), unique=True
    )
    previous_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("document_versions.id", ondelete="RESTRICT")
    )
    created_by_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    source: Mapped[bytes] = mapped_column(LargeBinary, deferred=True)
    source_size: Mapped[int]
    source_sha256: Mapped[str] = mapped_column(String(64))
    warnings: Mapped[dict[str, JsonValue]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        CheckConstraint("source_size > 0 AND source_size <= 10485760", name="source_size_valid"),
        CheckConstraint("octet_length(source) = source_size", name="source_size_matches"),
    )


class DocumentAsset(Base):
    __tablename__ = "document_assets"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    document_id: Mapped[UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="RESTRICT"), index=True
    )
    import_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("document_imports.id", ondelete="RESTRICT")
    )
    data: Mapped[bytes] = mapped_column(LargeBinary, deferred=True)
    media_type: Mapped[str] = mapped_column(String(32))
    width: Mapped[int]
    height: Mapped[int]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        CheckConstraint("media_type = 'image/png'", name="media_type_supported"),
        CheckConstraint("width > 0 AND height > 0", name="dimensions_positive"),
    )
