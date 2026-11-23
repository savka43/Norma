"""Bounded, deterministic structural/text diff. Moves appear as removal + addition."""

import hashlib
import json
from difflib import SequenceMatcher
from typing import Literal
from uuid import UUID

from fastapi import HTTPException
from pydantic import BaseModel, JsonValue

from app.api_v1.documents.structure import inline_text
from app.core.models import DocumentVersion

MAX_BLOCK_PAIRS = 2_000_000
MAX_TEXT_PAIRS = 1_000_000
type ChangeKind = Literal["equal", "added", "removed", "changed"]
OPCODE_KINDS: dict[str, ChangeKind] = {
    "equal": "equal",
    "insert": "added",
    "delete": "removed",
    "replace": "changed",
}


class DiffBlock(BaseModel):
    block_id: str
    kind: str
    text: str
    node: dict[str, JsonValue]


class TextChange(BaseModel):
    kind: ChangeKind
    before: str
    after: str


class BlockChange(BaseModel):
    kind: ChangeKind
    before: DiffBlock | None
    after: DiffBlock | None
    text_changes: list[TextChange]


class DiffResponse(BaseModel):
    base_version_id: UUID
    target_version_id: UUID
    template_changed: bool
    schema_changed: bool
    root_changed: bool
    changes: list[BlockChange]
    move_detection: Literal["not_performed"] = "not_performed"


def block_text(node: dict[str, JsonValue]) -> str:
    if node.get("type") in {"list", "table", "tablerow", "tablecell"}:
        children = node.get("children", [])
        return (
            "\n".join(block_text(child) for child in children if isinstance(child, dict))
            if isinstance(children, list)
            else ""
        )
    text = inline_text(node)
    # Nested lists inside listitems are separate text lines in the diff.
    children = node.get("children", [])
    if isinstance(children, list):
        for child in children:
            if isinstance(child, dict) and child.get("type") == "list":
                text += "\n" + block_text(child)
    return text


def top_blocks(content: dict[str, JsonValue]) -> list[DiffBlock]:
    root = content["root"]
    assert isinstance(root, dict)
    children = root["children"]
    assert isinstance(children, list)
    return [
        DiffBlock(block_id=str(i), kind=str(node["type"]), text=block_text(node), node=node)
        for i, node in enumerate(children)
        if isinstance(node, dict)
    ]


def signature(block: DiffBlock) -> str:
    return hashlib.sha256(
        json.dumps(block.node, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def text_diff(before: str, after: str, max_pairs: int = MAX_TEXT_PAIRS) -> list[TextChange]:
    if before == after:
        return [TextChange(kind="equal", before=before, after=after)]
    # For large changed blocks return the complete old/new text, without the
    # potentially quadratic fine-grained matcher. No source text is truncated.
    if len(before) * len(after) > max_pairs:
        return [TextChange(kind="changed", before=before, after=after)]
    result: list[TextChange] = []
    for tag, a, b, c, d in SequenceMatcher(None, before, after, autojunk=False).get_opcodes():
        kind = OPCODE_KINDS[tag]
        result.append(TextChange(kind=kind, before=before[a:b], after=after[c:d]))
    return result


def compare_versions(base: DocumentVersion, target: DocumentVersion) -> DiffResponse:
    before, after = top_blocks(base.content), top_blocks(target.content)
    if len(before) * len(after) > MAX_BLOCK_PAIRS:
        raise HTTPException(422, "Version diff block comparison budget exceeded")
    changes: list[BlockChange] = []
    text_budget = MAX_TEXT_PAIRS
    matcher = SequenceMatcher(
        None, [signature(b) for b in before], [signature(b) for b in after], autojunk=False
    )
    for tag, a, b, c, d in matcher.get_opcodes():
        count = max(b - a, d - c)
        for offset in range(count):
            left = before[a + offset] if a + offset < b else None
            right = after[c + offset] if c + offset < d else None
            kind: ChangeKind = (
                "equal"
                if tag == "equal"
                else "changed"
                if left and right
                else "removed"
                if left
                else "added"
            )
            left_text, right_text = left.text if left else "", right.text if right else ""
            details = text_diff(left_text, right_text, text_budget)
            cost = len(left_text) * len(right_text)
            if left_text != right_text and cost <= text_budget:
                text_budget -= cost
            changes.append(
                BlockChange(
                    kind=kind,
                    before=left,
                    after=right,
                    text_changes=details,
                )
            )
    return DiffResponse(
        base_version_id=base.id,
        target_version_id=target.id,
        template_changed=base.template_version_id != target.template_version_id,
        schema_changed=base.schema_version != target.schema_version,
        root_changed=root_properties(base.content) != root_properties(target.content),
        changes=changes,
    )


def root_properties(content: dict[str, JsonValue]) -> dict[str, JsonValue]:
    root = content["root"]
    assert isinstance(root, dict)
    return {key: value for key, value in root.items() if key != "children"}
