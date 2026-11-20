from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.api_v1.documents.lexical import LexicalContent, VersionOne
from app.core.validation import validate_stored_text


class DocumentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    template_version_id: UUID


class RevisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=1, le=2**31 - 2, strict=True)


class DocumentSave(RevisionRequest):
    content: LexicalContent
    schema_version: VersionOne
    template_version_id: UUID


class VersionCreate(RevisionRequest):
    comment: str | None = Field(default=None, max_length=2000)

    @field_validator("comment")
    @classmethod
    def validate_comment(cls, value: str | None) -> str | None:
        return validate_stored_text(value) if value is not None else None


class RestoreRequest(VersionCreate):
    version_id: UUID


class DocumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    thesis_id: UUID
    content: LexicalContent
    schema_version: int
    revision: int
    last_version_number: int
    template_version_id: UUID
    created_at: datetime
    updated_at: datetime


class LeaseResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    document_id: UUID
    lease_id: UUID
    holder_id: UUID
    acquired_at: datetime
    expires_at: datetime


class VersionSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    document_id: UUID
    number: int
    document_revision: int
    schema_version: int
    template_version_id: UUID
    created_by_id: UUID
    comment: str | None
    restored_from_id: UUID | None
    created_at: datetime


class VersionResponse(VersionSummary):
    content: LexicalContent


class VersionPage(BaseModel):
    items: list[VersionSummary]
    limit: int
    offset: int


class RestoreResponse(BaseModel):
    document: DocumentResponse
    version: VersionResponse
