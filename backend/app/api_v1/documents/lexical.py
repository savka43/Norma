from __future__ import annotations

import json
from typing import Annotated, Literal, Self, cast
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from app.core.validation import validate_stored_text

SCHEMA_VERSION = 2
MAX_CONTENT_BYTES = 2 * 1024 * 1024
MAX_CONTENT_OBJECTS = 50_000
MAX_JSON_DEPTH = 64
type VersionOne = Annotated[int, Field(strict=True, ge=1, le=1)]
type SchemaVersion = Annotated[int, Field(strict=True, ge=1, le=2)]
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


class ImageNode(Node):
    type: Literal["norma-image"]
    asset_id: UUID
    alt_text: str = Field(max_length=2000)


class LineBreakNode(Node):
    type: Literal["linebreak"]


type InlineNode = Annotated[TextNode | LineBreakNode | ImageNode, Field(discriminator="type")]


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
    children: list[
        Annotated[TextNode | LineBreakNode | ImageNode | ListNode, Field(discriminator="type")]
    ]


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


type TextBlockNode = Annotated[
    ParagraphNode | HeadingNode | QuoteNode | ListNode, Field(discriminator="type")
]


class TableCellNode(Element):
    type: Literal["tablecell"]
    headerState: int = Field(ge=0, le=3, strict=True)
    colSpan: int = Field(ge=1, le=100, strict=True)
    rowSpan: VersionOne
    backgroundColor: None
    children: Annotated[list[TextBlockNode], Field(min_length=1)]


class TableRowNode(Element):
    type: Literal["tablerow"]
    children: Annotated[list[TableCellNode], Field(min_length=1, max_length=100)]


class TableNode(Element):
    type: Literal["table"]
    children: Annotated[list[TableRowNode], Field(min_length=1, max_length=1000)]

    @model_validator(mode="after")
    def validate_grid(self) -> Self:
        widths = {sum(cell.colSpan for cell in row.children) for row in self.children}
        if len(widths) != 1 or max(widths) > 100:
            raise ValueError("A table must have a rectangular grid of at most 100 columns")
        return self


type BlockNode = Annotated[
    ParagraphNode | HeadingNode | QuoteNode | ListNode | TableNode, Field(discriminator="type")
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

    def image_ids(self) -> set[UUID]:
        return {
            UUID(str(node["asset_id"]))
            for node in content_nodes(self.stored())
            if node.get("type") == "norma-image"
        }

    def requires_v2(self) -> bool:
        return any(
            node.get("type") in ("table", "norma-image") for node in content_nodes(self.stored())
        )


def content_nodes(content: dict[str, JsonValue]) -> list[dict[str, JsonValue]]:
    result: list[dict[str, JsonValue]] = []
    stack: list[JsonValue] = [content["root"]]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            result.append(node)
            children = node.get("children")
            if isinstance(children, list):
                stack.extend(children)
    return result


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
