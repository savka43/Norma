from datetime import date, datetime
from typing import Annotated, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, StringConstraints, model_validator


class ThesisCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    student_id: UUID
    title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
    start_date: date
    due_date: date

    @model_validator(mode="after")
    def validate_dates(self) -> Self:
        if self.due_date < self.start_date:
            raise ValueError("due_date must be on or after start_date")
        return self


class ThesisResponse(BaseModel):
    id: UUID
    student_id: UUID
    supervisor_id: UUID
    title: str
    start_date: date
    due_date: date
    revision: int
    created_at: datetime
    total_stages: int
    completed_stages: int
    progress_percent: float | None
    overdue_stages: int
    is_overdue: bool
    as_of_date: date


class ThesisPage(BaseModel):
    items: list[ThesisResponse]
    limit: int
    offset: int
