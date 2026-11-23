from copy import deepcopy
from uuid import uuid4

import pytest
from fastapi import HTTPException
from pydantic import JsonValue

from app.api_v1.comments.schemas import CommentAnchor
from app.api_v1.comments.service import locate_anchor, validate_anchor
from app.api_v1.documents.diff import compare_versions, text_diff, top_blocks
from app.api_v1.documents.docx_import import element, text
from app.api_v1.documents.structure import semantic_blocks, utf16_slice
from app.core.models import DocumentVersion
from tests.document_helpers import content
from tests.formatting_helpers import formatting_content, paragraphs


def version(data: dict[str, JsonValue]) -> DocumentVersion:
    return DocumentVersion(
        id=uuid4(), document_id=uuid4(), content=data, schema_version=3, template_version_id=uuid4()
    )


def test_diff_preserves_table_list_image_and_formatting_changes() -> None:
    original = formatting_content()
    target = deepcopy(original)
    nodes = paragraphs(target)
    nodes[0]["tag"] = "h2"
    nodes[1]["format"] = "left"
    nodes.append(
        element(
            "paragraph",
            [
                {
                    "type": "norma-image",
                    "asset_id": str(uuid4()),
                    "alt_text": "Рисунок",
                    "version": 1,
                }
            ],
        )
    )
    first, second = version(original), version(target)
    report = compare_versions(first, second)
    assert report.template_changed and not report.schema_changed and not report.root_changed
    assert [item.kind for item in report.changes] == [
        "changed",
        "changed",
        "equal",
        "equal",
        "equal",
        "added",
    ]
    assert report.changes[0].before is not None and report.changes[0].before.node["tag"] == "h1"
    assert (
        report.changes[3].before is not None
        and report.changes[3].before.text == "Ячейка А\nЯчейка Б"
    )
    assert (
        report.changes[4].before is not None
        and report.changes[4].before.text == "Первый пункт\nВторой пункт"
    )
    assert report.changes[5].after is not None and report.changes[5].after.text == "\ufffc"
    assert first.content == original and second.content == target


def test_diff_removed_and_moved_blocks_never_lose_old_text() -> None:
    original: dict[str, JsonValue] = {
        "root": element(
            "root",
            [element("paragraph", [text(value)]) for value in ("Первый", "Удалённый", "Третий")],
        )
    }
    target: dict[str, JsonValue] = {
        "root": element(
            "root", [element("paragraph", [text(value)]) for value in ("Третий", "Первый")]
        )
    }
    report = compare_versions(version(original), version(target))
    assert report.move_detection == "not_performed"
    assert [item.before.text for item in report.changes if item.before] == [
        "Первый",
        "Удалённый",
        "Третий",
    ]
    assert [item.after.text for item in report.changes if item.after] == ["Третий", "Первый"]
    assert any(item.kind == "removed" for item in report.changes)
    assert any(item.kind == "added" for item in report.changes)


def test_diff_detects_root_schema_and_template_without_changing_versions() -> None:
    first, second = version(content()), version(content())
    root = second.content["root"]
    assert isinstance(root, dict)
    root["format"] = "right"
    second.schema_version = 2
    report = compare_versions(first, second)
    assert report.root_changed and report.schema_changed and report.template_changed
    assert [item.kind for item in report.changes] == ["equal"]


def test_large_block_text_diff_falls_back_without_truncating() -> None:
    before, after = "я" * 3000, "а" * 3000
    changes = text_diff(before, after)
    assert len(changes) == 1 and changes[0].kind == "changed"
    assert changes[0].before == before and changes[0].after == after


def test_diff_refuses_quadratic_block_work_before_matching() -> None:
    repeated: list[JsonValue] = [element("paragraph", [text("повтор")])] * 1500
    data: dict[str, JsonValue] = {"root": element("root", repeated)}
    with pytest.raises(HTTPException) as exc:
        compare_versions(version(data), version(data))
    assert exc.value.status_code == 422


def test_semantic_paths_include_table_cells_and_listitems() -> None:
    blocks = semantic_blocks(formatting_content())
    by_path = {block.block_id: block.text for block in blocks}
    assert by_path["3/0/0/0"] == "Ячейка А"
    assert by_path["4/1"] == "Второй пункт"
    validate_anchor(
        blocks, CommentAnchor(block_id="3/0/0/0", offset_start=0, offset_end=6), "Ячейка"
    )
    assert top_blocks(formatting_content())[3].kind == "table"


@pytest.mark.parametrize(
    ("start", "end", "expected"),
    [(1, 3, "😀"), (0, 1, "А"), (1, 2, None), (2, 3, None), (3, 9, None), (3, 3, None)],
)
def test_anchor_offsets_are_utf16_and_reject_split_surrogates(
    start: int, end: int, expected: str | None
) -> None:
    assert utf16_slice("А😀Б", start, end) == expected


def test_anchor_relocates_unique_quote_and_detaches_ambiguous_or_deleted_text() -> None:
    source = semantic_blocks(content("Исходный вывод"))
    anchor = CommentAnchor(block_id="0", offset_start=9, offset_end=14)
    assert locate_anchor(source, anchor, "вывод", source) == anchor
    moved = semantic_blocks(
        {
            "root": element(
                "root",
                [element("paragraph", [text("Новый блок")]), element("paragraph", [text("вывод")])],
            )
        }
    )
    located = locate_anchor(moved, anchor, "вывод", source)
    assert located is not None and located.block_id == "1" and located.offset_start == 0
    assert locate_anchor(semantic_blocks(content("нет фрагмента")), anchor, "вывод", source) is None
    assert locate_anchor(semantic_blocks(content("вывод и вывод")), anchor, "вывод", source) is None
