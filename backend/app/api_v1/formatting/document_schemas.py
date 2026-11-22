from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, JsonValue, field_validator

from app.api_v1.documents.schemas import DocumentResponse, RevisionRequest, VersionResponse
from app.api_v1.formatting.schemas import TemplateParameters


class FormattingIssue(BaseModel):
    path: str
    code: Literal["alignment_override", "indent_override", "text_effect_override"]
    actual: JsonValue
    expected: JsonValue


class FormattingReport(BaseModel):
    version_id: UUID
    template_version_id: UUID
    parameters: TemplateParameters
    conforms: bool
    issue_count: int
    issues: list[FormattingIssue]
    truncated: bool
    scope: Literal["semantic-formatting"] = "semantic-formatting"


class FormattingApply(RevisionRequest):
    model_config = ConfigDict(extra="forbid")
    template_version_id: UUID
    confirm_apply: Literal[True]

    @field_validator("confirm_apply", mode="before")
    @classmethod
    def explicit_confirmation(cls, value: object) -> object:
        if value is not True:
            raise ValueError("Explicit confirmation is required")
        return value


class FormattingApplied(BaseModel):
    document: DocumentResponse
    previous_version: VersionResponse
    version: VersionResponse
    corrected_issues: int


class ExportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    format: Literal["docx", "pdf"]
