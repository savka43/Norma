from __future__ import annotations

import json
from typing import Annotated, Literal, Self, cast

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from app.core.validation import validate_stored_text

SCHEMA_VERSION = 1
MAX_CONTENT_BYTES = 2 * 1024 * 1024
MAX_CONTENT_OBJECTS = 50_000
MAX_JSON_DEPTH = 64
type VersionOne = Annotated[int, Field(strict=True, ge=1, le=1)]
type TextFormat = Annotated[int, Field(strict=True, ge=0, le=2047)]


class Node(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: VersionOne


class TextNode(Node):
    type: Literal["text"]
    text: str
    format: TextFormat
    detail: int = Field(ge=0, le=3, strict=True)
    mode: Literal["normal", "token", "segmented"]
    style: Literal[""]


class LineBreakNode(Node):
    type: Literal["linebreak"]


type InlineNode = Annotated[TextNode | LineBreakNode, Field(discriminator="type")]


class Element(Node):
    direction: Literal["ltr", "rtl"] | None
    format: Literal["", "left", "start", "center", "right", "end", "justify"]
    indent: int = Field(ge=0, le=100, strict=True)
    textFormat: TextFormat = 0
    textStyle: Literal[""] = ""


class ParagraphNode(Element):
    type: Literal["paragraph"]
    children: list[InlineNode]


class HeadingNode(Element):
    type: Literal["heading"]
    tag: Literal["h1", "h2", "h3", "h4", "h5", "h6"]
    children: list[InlineNode]


class QuoteNode(Element):
    type: Literal["quote"]
    children: list[InlineNode]


class ListItemNode(Element):
    type: Literal["listitem"]
    value: int = Field(ge=1, le=2**31 - 1, strict=True)
    children: list[Annotated[TextNode | LineBreakNode | ListNode, Field(discriminator="type")]]


class ListNode(Element):
    type: Literal["list"]
    listType: Literal["bullet", "number"]
    tag: Literal["ul", "ol"]
    start: int = Field(ge=1, le=2**31 - 1, strict=True)
    children: list[ListItemNode]

    @model_validator(mode="after")
    def validate_tag(self) -> Self:
        if self.tag != ("ol" if self.listType == "number" else "ul"):
            raise ValueError("List tag does not match listType")
        return self


type BlockNode = Annotated[
    ParagraphNode | HeadingNode | QuoteNode | ListNode, Field(discriminator="type")
]


class RootNode(Element):
    type: Literal["root"]
    children: Annotated[list[BlockNode], Field(min_length=1)]


class LexicalContent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    root: RootNode

    @model_validator(mode="before")
    @classmethod
    def validate_budget(cls, value: object) -> object:
        # Guard before recursive Pydantic parsing, including unknown/deep fields.
        stack: list[tuple[object, int]] = [(value, 0)]
        objects = 0
        while stack:
            item, depth = stack.pop()
            if depth > MAX_JSON_DEPTH:
                raise ValueError("Document nesting limit exceeded")
            if isinstance(item, dict):
                objects += 1
                stack.extend((child, depth + 1) for child in cast(dict[str, object], item).values())
            elif isinstance(item, list):
                stack.extend((child, depth + 1) for child in cast(list[object], item))
            elif isinstance(item, str):
                validate_stored_text(item)
            if objects > MAX_CONTENT_OBJECTS:
                raise ValueError("Document node limit exceeded")
        encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        if len(encoded) > MAX_CONTENT_BYTES:
            raise ValueError("Document size limit exceeded")
        return value

    def stored(self) -> dict[str, JsonValue]:
        return cast(dict[str, JsonValue], self.model_dump(mode="json", exclude_unset=True))


def empty_content() -> dict[str, JsonValue]:
    return LexicalContent.model_validate(
        {
            "root": {
                "type": "root",
                "version": 1,
                "direction": None,
                "format": "",
                "indent": 0,
                "children": [
                    {
                        "type": "paragraph",
                        "version": 1,
                        "direction": None,
                        "format": "",
                        "indent": 0,
                        "children": [],
                    }
                ],
            }
        }
    ).stored()
