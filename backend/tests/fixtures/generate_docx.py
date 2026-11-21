"""Generate a synthetic interoperability fixture with python-docx (no user documents)."""

import io
from pathlib import Path

from docx import Document
from docx.shared import Inches
from PIL import Image


def main() -> None:
    document = Document()
    document.add_heading("Синтетическая ВКР", level=1)
    paragraph = document.add_paragraph("Обычный текст; ")
    paragraph.add_run("полужирный").bold = True
    paragraph.add_run(" и курсив").italic = True
    document.add_paragraph("Маркированный пункт", style="List Bullet")
    document.add_paragraph("Нумерованный пункт", style="List Number")
    table = document.add_table(rows=2, cols=2)
    for row_index, row in enumerate(table.rows):
        for column_index, cell in enumerate(row.cells):
            cell.text = f"Ячейка {row_index * 2 + column_index + 1}"
    binary = io.BytesIO()
    Image.new("RGB", (12, 8), color="blue").save(binary, format="PNG")
    binary.seek(0)
    document.add_picture(binary, width=Inches(1))
    document.sections[0].header.paragraphs[0].text = "Неподдержанный колонтитул"
    document.add_paragraph("Конец документа")
    document.save(str(Path(__file__).with_name("synthetic-import.docx")))


if __name__ == "__main__":
    main()
