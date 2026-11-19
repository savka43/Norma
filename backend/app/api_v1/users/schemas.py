from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

SearchQuery = Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=100)]


class StudentSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    full_name: str
    email: str
    academic_group: str


class StudentSearchParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: SearchQuery
    limit: int = Field(default=20, ge=1, le=50)
    offset: int = Field(default=0, ge=0, le=2**63 - 1)


class StudentPage(BaseModel):
    items: list[StudentSummary]
    limit: int
    offset: int
