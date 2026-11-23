from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, field_validator

from app.core.models import CheckStatus


class CheckCreate(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    confirm_demo_document: bool

    @field_validator("confirm_demo_document")
    @classmethod
    def require_confirmation(cls, value: bool) -> bool:
        if not value:
            raise ValueError("Confirm that the version contains only synthetic demo text")
        return value


class CheckReport(BaseModel):
    report_number: int | None = None
    originality_percent: float | None = None
    similarity_percent: float | None = None
    citation_percent: float | None = None
    self_citation_percent: float | None = None
    is_suspicious: bool | None = None
    short_report_url: str | None = None
    readonly_report_url: str | None = None


class CheckResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    version_id: UUID
    requested_by_id: UUID
    status: CheckStatus
    external_id: int | None
    error_code: str | None
    error_detail: str | None
    created_at: datetime
    updated_at: datetime
    finished_at: datetime | None


class CheckPage(BaseModel):
    items: list[CheckResponse]
    limit: int
    offset: int
