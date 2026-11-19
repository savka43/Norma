from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints


class GroupCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]
    academic_year: int = Field(ge=1, le=9998, strict=True)


class GroupResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    supervisor_id: UUID
    name: str
    academic_year: int
    created_at: datetime


class PageParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    limit: int = Field(default=50, ge=1, le=100)
    offset: int = Field(default=0, ge=0, le=2**63 - 1)


class GroupPage(BaseModel):
    items: list[GroupResponse]
    limit: int
    offset: int


class StudentAdd(BaseModel):
    model_config = ConfigDict(extra="forbid")

    student_id: UUID


class MembershipResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    student_id: UUID
    group_id: UUID
    joined_at: datetime
