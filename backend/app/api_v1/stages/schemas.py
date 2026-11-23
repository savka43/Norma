from datetime import date, datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.api_v1.documents.schemas import VersionCreate
from app.api_v1.theses.schemas import ThesisResponse
from app.api_v1.users.schemas import StudentSummary
from app.core.models import StageStatus


class StageWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]
    position: int = Field(ge=1, le=2**31 - 1, strict=True)
    due_date: date
    expected_revision: int = Field(ge=1, le=2**31 - 2, strict=True)


class StageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    thesis_id: UUID
    name: str
    position: int
    due_date: date
    status: StageStatus
    created_at: datetime
    is_overdue: bool
    submitted_version_id: UUID | None = None


class StagePage(BaseModel):
    items: list[StageResponse]
    revision: int
    as_of_date: date


class StageEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    stage_id: UUID
    actor_id: UUID
    thesis_revision: int
    kind: str
    before: dict[str, str | int] | None
    after: dict[str, str | int]
    created_at: datetime
    version_id: UUID | None = None
    reason: str | None = None


class StageHistoryPage(BaseModel):
    items: list[StageEventResponse]
    limit: int
    offset: int


class StudentProgress(BaseModel):
    student: StudentSummary
    thesis: ThesisResponse | None
    stages: list[StageResponse]


class GroupProgressPage(BaseModel):
    items: list[StudentProgress]
    limit: int
    offset: int
    as_of_date: date


class StageSubmit(VersionCreate):
    expected_document_revision: int = Field(ge=1, le=2**31 - 2, strict=True)


class StageDecision(VersionCreate):
    submitted_version_id: UUID


class StageActionResponse(BaseModel):
    stage: StageResponse
    revision: int
    event: StageEventResponse


class SubmissionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    stage_id: UUID
    version_id: UUID
    submitted_by_id: UUID
    thesis_revision: int
    scope: Literal["document", "chapter"]
    created_at: datetime


class SubmissionPage(BaseModel):
    items: list[SubmissionResponse]
    limit: int
    offset: int
