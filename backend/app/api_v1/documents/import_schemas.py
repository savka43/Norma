from datetime import datetime
from typing import Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.api_v1.documents.schemas import DocumentResponse, VersionResponse


class ImportParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=1, le=2**31 - 2)
    confirm_replace: bool

    @model_validator(mode="after")
    def require_confirmation(self) -> Self:
        if not self.confirm_replace:
            raise ValueError("Explicit confirmation to replace the document is required")
        return self


class ImportSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    document_id: UUID
    version_id: UUID
    previous_version_id: UUID
    created_by_id: UUID
    source_size: int
    source_sha256: str
    warnings: dict[str, int]
    created_at: datetime


class ImportResponse(BaseModel):
    document: DocumentResponse
    version: VersionResponse
    import_record: ImportSummary


class ImportPage(BaseModel):
    items: list[ImportSummary]
    limit: int
    offset: int
