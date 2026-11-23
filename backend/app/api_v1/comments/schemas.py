from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from app.api_v1.documents.schemas import RevisionRequest
from app.api_v1.supervisor_groups.schemas import PageParams
from app.core.validation import validate_stored_text


class CommentAnchor(BaseModel):
    model_config = ConfigDict(extra="forbid")
    block_id: str = Field(pattern=r"^\d+(?:/\d+)*$", max_length=512)
    offset_start: int = Field(ge=0, le=2**31 - 1, strict=True)
    offset_end: int = Field(ge=1, le=2**31 - 1, strict=True)

    @model_validator(mode="after")
    def check_range(self) -> "CommentAnchor":
        if self.offset_end <= self.offset_start:
            raise ValueError("Anchor end must follow start")
        return self


class CommentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    body: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=10000)]
    quote: str = Field(min_length=1, max_length=10000)
    anchor: CommentAnchor

    @field_validator("body", "quote")
    @classmethod
    def check_text(cls, value: str) -> str:
        return validate_stored_text(value)


class CommentResolve(RevisionRequest):
    status: Literal["resolved"]


class CommentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    version_id: UUID
    author_id: UUID
    body: str
    quote: str
    anchor: CommentAnchor
    status: Literal["open", "resolved"]
    revision: int
    created_at: datetime
    # Original anchor never changes. This projection is relative to the live document.
    current_anchor: CommentAnchor | None = None
    is_detached: bool = False


class CommentPage(BaseModel):
    items: list[CommentResponse]
    limit: int
    offset: int


class CommentListParams(PageParams):
    include_resolved: bool = False
    include_detached: bool = False


class CommentEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    comment_id: UUID
    actor_id: UUID
    revision: int
    status: str
    created_at: datetime


class CommentHistoryPage(BaseModel):
    items: list[CommentEventResponse]
    limit: int
    offset: int
