"""Generate synthetic export fixtures for visual QA; never uses user documents."""

import sys
from copy import deepcopy
from io import BytesIO
from pathlib import Path
from typing import cast
from uuid import UUID

from PIL import Image, ImageDraw
from pydantic import JsonValue

from app.api_v1.documents.docx_import import element, text
from app.api_v1.documents.export.docx import ImageAsset, render_docx
from app.api_v1.documents.lexical import LexicalContent
from app.api_v1.formatting.presets import gost_parameters
from tests.formatting_helpers import formatting_content, paragraphs


def generate(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    params = gost_parameters()
    params.body.font_family = "Liberation Serif"
    for style in [*params.headings, params.caption, params.list, params.table]:
        style.font_family = "Liberation Serif"
    data = formatting_content()
    blocks = paragraphs(data)
    # Nested numbering starts at 3 and 5 to make accidental restarts visible.
    listing = blocks[-1]
    items = cast(list[JsonValue], listing["children"])
    nested = deepcopy(listing)
    nested["start"] = 5
    nested["children"] = [{**element("listitem", [text("Вложенный пункт")]), "value": 5}]
    items.insert(1, {**element("listitem", [nested]), "value": 4})
    asset_id = UUID("00000000-0000-0000-0000-000000000001")
    bitmap = Image.new("RGB", (800, 240), "#edf2f7")
    draw = ImageDraw.Draw(bitmap)
    for index in range(3):
        draw.rounded_rectangle(
            (30 + index * 260, 60, 250 + index * 260, 180),
            radius=8,
            fill=(30 + index * 50, 90, 130),
        )
    image = BytesIO()
    bitmap.save(image, "PNG")
    blocks.extend(
        [
            element(
                "paragraph",
                [
                    {
                        "type": "norma-image",
                        "version": 1,
                        "asset_id": str(asset_id),
                        "alt_text": "Синтетическая схема",
                    }
                ],
            ),
            {
                **element("norma-caption", [text("Рисунок 1 - Синтетическая схема")]),
                "kind": "figure",
            },
        ]
    )
    assets = {asset_id: ImageAsset(image.getvalue(), 800, 240)}
    (directory / "short.docx").write_bytes(
        render_docx(LexicalContent.model_validate(data), params, assets)
    )
    prose = (
        "Система сопровождения ВКР сохраняет контрольные версии документа и параметры "
        "оформления. Руководитель проверяет зафиксированный текст, а последующие правки "
        "сохраняются отдельно. Этот искусственный абзац проверяет переносы строк, "
        "интервалы и сохранность кириллицы при экспорте."
    )
    for index in range(28):
        blocks.append(element("paragraph", [text(f"{index + 1}. {prose}")]))
    # A table long enough to cross a page boundary, with a repeated header.
    table = deepcopy(blocks[3])
    rows = cast(list[JsonValue], table["children"])
    for cell in cast(list[dict[str, JsonValue]], cast(dict[str, JsonValue], rows[0])["children"]):
        cell["headerState"] = 1
    for index in range(22):
        row = deepcopy(rows[0])
        cells = cast(list[dict[str, JsonValue]], cast(dict[str, JsonValue], row)["children"])
        for column, cell in enumerate(cells):
            cell["headerState"] = 0
            cell["children"] = [
                element("paragraph", [text(f"Строка {index + 1}, столбец {column + 1}")])
            ]
        rows.append(row)
    blocks.extend(
        [
            {**element("norma-caption", [text("Таблица 2 - Длинная таблица")]), "kind": "table"},
            table,
        ]
    )
    data_model = LexicalContent.model_validate(data)
    (directory / "long.docx").write_bytes(render_docx(data_model, params, assets))
    params.orientation = "landscape"
    params.body.font_size_pt = 12
    params.margins.left_mm = 20
    params.margins.right_mm = 20
    (directory / "landscape.docx").write_bytes(render_docx(data_model, params, assets))


if __name__ == "__main__":
    generate(Path(sys.argv[1]))
