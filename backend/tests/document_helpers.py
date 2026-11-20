from typing import cast

from pydantic import JsonValue

from app.api_v1.documents.lexical import LexicalContent


def content(text: str = "Текст ВКР") -> dict[str, JsonValue]:
    return cast(
        dict[str, JsonValue],
        LexicalContent.model_validate(
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
                            "children": [
                                {
                                    "type": "text",
                                    "version": 1,
                                    "text": text,
                                    "format": 1,
                                    "detail": 0,
                                    "mode": "normal",
                                    "style": "",
                                }
                            ],
                        }
                    ],
                }
            }
        ).model_dump(mode="json"),
    )


def parameters(font_size: int = 14) -> dict[str, JsonValue]:
    style: dict[str, JsonValue] = {
        "font_family": "Times New Roman",
        "font_size_pt": font_size,
        "line_spacing": 1.5,
        "first_line_indent_mm": 12.5,
        "space_before_pt": 0,
        "space_after_pt": 0,
        "alignment": "justify",
        "bold": False,
        "italic": False,
    }
    return {
        "schema_version": 1,
        "page_format": "A4",
        "orientation": "portrait",
        "margins": {"top_mm": 20, "bottom_mm": 20, "left_mm": 30, "right_mm": 15},
        "body": style.copy(),
        "headings": [style.copy() for _ in range(6)],
        "caption": style.copy(),
        "list": style.copy(),
        "table": style.copy(),
        "page_number_start": 1,
    }
