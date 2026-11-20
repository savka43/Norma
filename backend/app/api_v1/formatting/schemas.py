from datetime import datetime
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)

from app.core.validation import validate_stored_text

type Name = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=255),
    AfterValidator(validate_stored_text),
]
type Mm = Annotated[float, Field(ge=0, le=100, allow_inf_nan=False)]
type Pt = Annotated[float, Field(ge=6, le=72, allow_inf_nan=False)]


class ParametersModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Margins(ParametersModel):
    top_mm: Mm
    bottom_mm: Mm
    left_mm: Mm
    right_mm: Mm


class TextStyle(ParametersModel):
    font_family: Annotated[str, StringConstraints(pattern=r"^[\w \-]{1,100}$")]
    font_size_pt: Pt
    line_spacing: float = Field(ge=1, le=3, allow_inf_nan=False)
    first_line_indent_mm: Mm
    space_before_pt: float = Field(ge=0, le=100, allow_inf_nan=False)
    space_after_pt: float = Field(ge=0, le=100, allow_inf_nan=False)
    alignment: Literal["left", "center", "right", "justify"]
    bold: bool = Field(strict=True)
    italic: bool = Field(strict=True)


class TemplateParameters(ParametersModel):
    schema_version: int = Field(ge=1, le=1, strict=True)
    page_format: Literal["A4"]
    orientation: Literal["portrait", "landscape"]
    margins: Margins
    body: TextStyle
    headings: Annotated[list[TextStyle], Field(min_length=6, max_length=6)]
    caption: TextStyle
    list: TextStyle
    table: TextStyle
    page_number_start: int = Field(ge=1, le=100_000, strict=True)

    @model_validator(mode="after")
    def validate_print_area(self) -> Self:
        width, height = (210, 297) if self.orientation == "portrait" else (297, 210)
        if self.margins.left_mm + self.margins.right_mm >= width:
            raise ValueError("Margins leave no printable width")
        if self.margins.top_mm + self.margins.bottom_mm >= height:
            raise ValueError("Margins leave no printable height")
        return self


class TemplateCreate(ParametersModel):
    name: Name
    parameters: TemplateParameters


class TemplateVersionCreate(ParametersModel):
    expected_version: int = Field(ge=1, le=2**31 - 2, strict=True)
    parameters: TemplateParameters


class TemplateResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    supervisor_id: UUID
    name: str
    latest_version: int
    created_at: datetime


class TemplateVersionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    template_id: UUID
    number: int
    parameters: TemplateParameters
    created_at: datetime


class TemplateCreatedResponse(BaseModel):
    template: TemplateResponse
    version: TemplateVersionResponse


class TemplatePage(BaseModel):
    items: list[TemplateResponse]
    limit: int
    offset: int


class TemplateVersionPage(BaseModel):
    items: list[TemplateVersionResponse]
    limit: int
    offset: int
