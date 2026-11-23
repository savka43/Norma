from typing import cast
from uuid import UUID

from pydantic import JsonValue


def chapter_blocks(content: dict[str, JsonValue]) -> dict[UUID, list[JsonValue]]:
    """Return bound chapters in document order, including each start heading."""
    root = cast(dict[str, JsonValue], content["root"])
    chapters: dict[UUID, list[JsonValue]] = {}
    chapter: list[JsonValue] | None = None
    for block in cast(list[dict[str, JsonValue]], root["children"]):
        if block["type"] == "heading" and block.get("tag") == "h1":
            state = block.get("$")
            chapter = None
            if isinstance(state, dict):
                chapter = []
                chapters[UUID(str(state["normaStageId"]))] = chapter
        if chapter is not None:
            chapter.append(block)
    return chapters


def preserves_chapters(
    before: dict[str, JsonValue], after: dict[str, JsonValue], protected: set[UUID]
) -> bool:
    before_root = cast(dict[str, JsonValue], before["root"])
    after_root = cast(dict[str, JsonValue], after["root"])
    if {key: value for key, value in before_root.items() if key != "children"} != {
        key: value for key, value in after_root.items() if key != "children"
    }:
        return False
    before_chapters = chapter_blocks(before)
    after_chapters = chapter_blocks(after)
    before_order = [stage_id for stage_id in before_chapters if stage_id in protected]
    after_order = [stage_id for stage_id in after_chapters if stage_id in protected]
    return (
        len(before_order) == len(protected)
        and before_order == after_order
        and all(before_chapters[stage_id] == after_chapters[stage_id] for stage_id in before_order)
    )
