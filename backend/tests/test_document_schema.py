import json
from copy import deepcopy
from pathlib import Path
from typing import cast

import pytest
from pydantic import JsonValue, ValidationError

from app.api_v1.documents import lexical
from app.api_v1.formatting.schemas import TemplateParameters
from tests.document_helpers import content, parameters


def test_real_lexical_export_round_trip() -> None:
    # Generated and read back by @lexical/headless 0.53.0, not a hand-drawn JSON example.
    data = json.loads((Path(__file__).parent / "fixtures/lexical-0.53.0.json").read_text())
    assert lexical.LexicalContent.model_validate(data).stored() == data


@pytest.mark.parametrize(
    "node",
    [
        {"type": "html", "html": "<script>alert(1)</script>", "version": 1},
        {"type": "table", "version": 1, "children": []},
        {
            "type": "text",
            "version": 1,
            "text": "Текст",
            "format": 0,
            "detail": 0,
            "mode": "normal",
            "style": "",
        },
        {
            "type": "paragraph",
            "version": 2,
            "direction": None,
            "format": "",
            "indent": 0,
            "children": [],
        },
        {
            "type": "paragraph",
            "version": True,
            "direction": None,
            "format": "",
            "indent": 0,
            "children": [],
        },
    ],
)
def test_rejects_unknown_nodes_and_invalid_structure(node: dict[str, object]) -> None:
    data = content()
    root = cast(dict[str, JsonValue], data["root"])
    root["children"] = cast(JsonValue, [node])
    with pytest.raises(ValidationError):
        lexical.LexicalContent.model_validate(data)


@pytest.mark.parametrize(
    "patch",
    [
        {"style": "color: red"},
        {"format": True},
        {"format": 2048},
        {"text": "bad\x00text"},
        {"text": "bad\ud800text"},
        {"html": "<b>text</b>"},
    ],
)
def test_text_fields_are_validated(patch: dict[str, object]) -> None:
    data = content()
    root = cast(dict[str, JsonValue], data["root"])
    paragraph = cast(dict[str, JsonValue], cast(list[JsonValue], root["children"])[0])
    text = cast(dict[str, JsonValue], cast(list[JsonValue], paragraph["children"])[0])
    text.update(cast(dict[str, JsonValue], patch))
    with pytest.raises(ValidationError):
        lexical.LexicalContent.model_validate(data)


def test_content_size_node_and_depth_limits(monkeypatch: pytest.MonkeyPatch) -> None:
    with monkeypatch.context() as limits:
        limits.setattr(lexical, "MAX_CONTENT_BYTES", 100)
        with pytest.raises(ValidationError, match="size limit"):
            lexical.LexicalContent.model_validate(content("x" * 100))
    with monkeypatch.context() as limits:
        limits.setattr(lexical, "MAX_CONTENT_OBJECTS", 2)
        with pytest.raises(ValidationError, match="node limit"):
            lexical.LexicalContent.model_validate(content())
    nested: dict[str, object] = {}
    for _ in range(lexical.MAX_JSON_DEPTH + 1):
        nested = {"nested": nested}
    with pytest.raises(ValidationError, match="nesting limit"):
        lexical.LexicalContent.model_validate(nested)


def test_empty_root_cannot_be_saved_as_an_unopenable_editor_state() -> None:
    with pytest.raises(ValidationError):
        lexical.LexicalContent.model_validate(
            {
                "root": {
                    "type": "root",
                    "version": 1,
                    "direction": None,
                    "format": "",
                    "indent": 0,
                    "children": [],
                }
            }
        )


@pytest.mark.parametrize(
    "patch",
    [
        {"page_format": "A3"},
        {"orientation": "unknown"},
        {"schema_version": 2},
        {"margins": {"top_mm": -1, "bottom_mm": 20, "left_mm": 30, "right_mm": 15}},
        {"headings": []},
        {"page_number_start": True},
        {"unexpected": "value"},
    ],
)
def test_template_parameters_are_validated(patch: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        TemplateParameters.model_validate({**parameters(), **patch})


def test_template_style_validates_fonts_numbers_and_custom_values() -> None:
    for invalid in ("font: <script>", "a; color:red", "a' onclick='x"):
        data = deepcopy(parameters())
        cast(dict[str, JsonValue], data["body"])["font_family"] = invalid
        with pytest.raises(ValidationError):
            TemplateParameters.model_validate(data)
    for invalid in (float("inf"), float("nan"), -1, 0):
        data = deepcopy(parameters())
        cast(dict[str, JsonValue], data["body"])["font_size_pt"] = invalid
        with pytest.raises(ValidationError):
            TemplateParameters.model_validate(data)
    assert TemplateParameters.model_validate(parameters(18)).body.font_size_pt == 18
