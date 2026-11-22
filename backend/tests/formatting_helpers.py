from typing import cast

from pydantic import JsonValue

from app.api_v1.documents.docx_import import element, text
from app.api_v1.documents.lexical import LexicalContent


def formatting_content() -> dict[str, JsonValue]:
    heading = element("heading", [text("Глава 1. Проверка оформления")])
    heading["tag"] = "h1"
    paragraph = element("paragraph", [text("Текст ", 1), text("с выделением", 2)])
    paragraph.update(format="right", indent=3)
    caption = element("norma-caption", [text("Таблица 1 - Результаты")])
    caption["kind"] = "table"
    row = element(
        "tablerow",
        [
            {
                **element("tablecell", [element("paragraph", [text("Ячейка А")])]),
                "headerState": 0,
                "colSpan": 1,
                "rowSpan": 1,
                "backgroundColor": None,
            },
            {
                **element("tablecell", [element("paragraph", [text("Ячейка Б")])]),
                "headerState": 0,
                "colSpan": 1,
                "rowSpan": 1,
                "backgroundColor": None,
            },
        ],
    )
    listing = {
        **element(
            "list",
            [
                {**element("listitem", [text("Первый пункт")]), "value": 3},
                {**element("listitem", [text("Второй пункт")]), "value": 4},
            ],
        ),
        "listType": "number",
        "tag": "ol",
        "start": 3,
    }
    return LexicalContent.model_validate(
        {
            "root": element(
                "root", [heading, paragraph, caption, element("table", [row]), listing]
            ),
        }
    ).stored()


def paragraphs(content: dict[str, JsonValue]) -> list[dict[str, JsonValue]]:
    return cast(list[dict[str, JsonValue]], cast(dict[str, JsonValue], content["root"])["children"])
