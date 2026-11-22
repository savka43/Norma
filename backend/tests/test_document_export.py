# pyright: reportUnknownMemberType=false, reportPrivateUsage=false
import shutil
import sys
from io import BytesIO
from pathlib import Path
from typing import cast
from uuid import uuid4
from zipfile import ZipFile

import pytest
from docx import Document
from fastapi import HTTPException
from pydantic import JsonValue, ValidationError
from pypdf import PdfReader

from app.api_v1.documents.docx_import import convert_docx, element, text
from app.api_v1.documents.export import pdf
from app.api_v1.documents.export.docx import ImageAsset, render_docx
from app.api_v1.documents.lexical import LexicalContent, content_nodes
from app.api_v1.documents.schemas import DocumentSave
from app.api_v1.formatting import document_service
from app.api_v1.formatting.document_schemas import FormattingApply
from app.api_v1.formatting.normalize import formatting_issues, normalize
from app.api_v1.formatting.presets import gost_parameters
from app.core.config import Settings
from tests.formatting_helpers import formatting_content, paragraphs


def test_normalization_preserves_text_order_structure_and_emphasis() -> None:
    original = formatting_content()
    params = gost_parameters()
    issues = formatting_issues(original, params)
    assert {issue.code for issue in issues} == {"alignment_override", "indent_override"}
    normalized = normalize(original)
    assert paragraphs(original)[1]["format"] == "right"
    assert not formatting_issues(normalized, params)
    before = [(n["type"], n.get("text"), n.get("kind")) for n in content_nodes(original)]
    after = [(n["type"], n.get("text"), n.get("kind")) for n in content_nodes(normalized)]
    assert before == after
    assert normalize(normalized) == normalized
    for node in content_nodes(normalized):
        if node["type"] == "text" and node["text"] == "Текст ":
            assert node["format"] == 1


def test_check_uses_custom_template_alignment_and_text_effects() -> None:
    data = formatting_content()
    params = gost_parameters()
    params.body.alignment = "right"
    for node in content_nodes(data):
        if node["type"] == "text":
            node["format"] = 16 | 128 | 1
    issues = formatting_issues(data, params)
    assert not any(i.code == "alignment_override" for i in issues)
    assert any(i.code == "text_effect_override" and i.expected == 1 for i in issues)
    assert not formatting_issues(normalize(data), params)


@pytest.mark.parametrize("version", [1, 2])
def test_captions_require_v3_without_changing_old_snapshots(version: int) -> None:
    with pytest.raises(ValidationError, match="captions require schema_version 3"):
        DocumentSave.model_validate(
            {
                "content": formatting_content(),
                "schema_version": version,
                "template_version_id": str(uuid4()),
                "expected_revision": 1,
            }
        )


@pytest.mark.parametrize("confirmation", [False, 1, "true", None])
def test_formatting_requires_explicit_confirmation(confirmation: object) -> None:
    with pytest.raises(ValidationError):
        FormattingApply.model_validate(
            {
                "expected_revision": 1,
                "template_version_id": str(uuid4()),
                "confirm_apply": confirmation,
            }
        )


def test_docx_styles_geometry_captions_lists_and_table_keep_user_content() -> None:
    params = gost_parameters()
    params.body.font_size_pt = 18
    params.headings[0].font_size_pt = 22
    params.caption.font_size_pt = 11
    params.list.first_line_indent_mm = 9
    params.table.font_size_pt = 10
    params.orientation = "landscape"
    params.margins.left_mm = 17
    params.page_number_start = 7
    binary = render_docx(LexicalContent.model_validate(formatting_content()), params, {})
    document = Document(BytesIO(binary))
    section = document.sections[0]
    assert section.page_width is not None and section.page_height is not None
    assert section.page_width.mm == pytest.approx(297, abs=0.1)
    assert section.page_height.mm == pytest.approx(210, abs=0.1)
    assert section.left_margin is not None and section.left_margin.mm == pytest.approx(17, abs=0.1)
    assert document.paragraphs[1].text == "Текст с выделением"
    assert document.paragraphs[1].runs[0].bold
    assert document.paragraphs[1].runs[1].italic
    assert document.paragraphs[2].style is not None
    assert document.paragraphs[2].style.name == "Norma Table Caption"
    assert document.tables[0].cell(0, 1).text == "Ячейка Б"
    with ZipFile(BytesIO(binary)) as package:
        styles = package.read("word/styles.xml").decode()
        assert 'w:val="36"' in styles and 'w:val="44"' in styles
        assert 'w:val="22"' in styles and 'w:val="20"' in styles
        assert 'w:start="7"' in package.read("word/document.xml").decode()
        assert 'w:val="3"' in package.read("word/numbering.xml").decode()
        assert "PAGE" in package.read("word/footer1.xml").decode()
        assert not any(
            'TargetMode="External"' in package.read(n).decode()
            for n in package.namelist()
            if n.endswith(".rels")
        )


def test_docx_embeds_image_bytes_alt_text_and_scales_to_printable_area() -> None:
    from PIL import Image

    buffer = BytesIO()
    Image.new("RGB", (800, 400), "blue").save(buffer, format="PNG")
    asset_id = uuid4()
    data = formatting_content()
    paragraphs(data).insert(
        1,
        {
            "type": "paragraph",
            "version": 1,
            "direction": None,
            "format": "",
            "indent": 0,
            "children": [
                {
                    "type": "norma-image",
                    "version": 1,
                    "asset_id": str(asset_id),
                    "alt_text": "Схема системы",
                }
            ],
        },
    )
    binary = render_docx(
        LexicalContent.model_validate(data),
        gost_parameters(),
        {asset_id: ImageAsset(buffer.getvalue(), 800, 400)},
    )
    document = Document(BytesIO(binary))
    assert len(document.inline_shapes) == 1
    assert document.inline_shapes[0].width.mm <= 210 - 30 - 15
    assert document.paragraphs[1].style is not None
    assert document.paragraphs[1].style.name == "Norma Image"
    with ZipFile(BytesIO(binary)) as package:
        assert package.read("word/media/image1.png") == buffer.getvalue()
        assert "Схема системы" in package.read("word/document.xml").decode()
        # Without explicit distances LibreOffice adds 3.2 mm at each side,
        # shifting even a centered, correctly sized image beyond the right margin.
        assert 'distL="0"' in package.read("word/document.xml").decode()
        assert 'distR="0"' in package.read("word/document.xml").decode()


def test_pdf_missing_converter_is_explicit(settings: Settings) -> None:
    settings.pdf_converter = "norma-nonexistent-converter"
    with pytest.raises(HTTPException) as error:
        document_service.build_export(
            LexicalContent.model_validate(formatting_content()),
            gost_parameters(),
            {},
            "pdf",
            settings,
        )
    assert error.value.status_code == 503


def test_own_docx_reimport_preserves_semantic_caption_and_nested_list_start() -> None:
    data = formatting_content()
    listing = paragraphs(data)[-1]
    nested = {
        **element("list", [{**element("listitem", [text("Вложенный")]), "value": 5}]),
        "listType": "number",
        "tag": "ol",
        "start": 5,
    }
    items = cast(list[JsonValue], listing["children"])
    items.insert(1, {**element("listitem", [nested]), "value": 4})
    output = render_docx(LexicalContent.model_validate(data), gost_parameters(), {})
    imported = convert_docx(output)
    nodes = content_nodes(imported.content.stored())
    assert any(n["type"] == "norma-caption" and n["kind"] == "table" for n in nodes)
    lists = [n for n in nodes if n["type"] == "list"]
    assert {int(str(n["start"])) for n in lists} == {3, 5}
    assert any(n["type"] == "text" and n["text"] == "Вложенный" for n in nodes)


def test_pdf_timeout_is_bounded_and_temporary_files_are_cleaned(
    tmp_path: Path,
) -> None:
    observed = tmp_path / "directory.txt"
    converter = tmp_path / "slow-converter"
    converter.write_text(
        f"#!{sys.executable}\nimport sys, time\nfrom pathlib import Path\n"
        f"Path({str(observed)!r}).write_text(str(Path(sys.argv[-1]).parent))\ntime.sleep(60)\n"
    )
    converter.chmod(0o700)
    with pytest.raises(pdf.ConversionFailed, match="timed out"):
        pdf.render_pdf(b"docx", str(converter), 1, 1024)
    assert observed.is_file() and not Path(observed.read_text()).exists()


def test_export_capacity_limit_rejects_busy_request_and_recovers(settings: Settings) -> None:
    first = document_service.EXPORT_SLOTS.acquire(blocking=False)
    second = document_service.EXPORT_SLOTS.acquire(blocking=False)
    assert first and second
    try:
        with pytest.raises(HTTPException) as error:
            document_service.build_export(
                LexicalContent.model_validate(formatting_content()),
                gost_parameters(),
                {},
                "docx",
                settings,
            )
        assert error.value.status_code == 503
    finally:
        document_service.EXPORT_SLOTS.release()
        document_service.EXPORT_SLOTS.release()
    assert document_service.build_export(
        LexicalContent.model_validate(formatting_content()), gost_parameters(), {}, "docx", settings
    )[0].startswith(b"PK")


def test_real_pdf_conversion_keeps_cyrillic_table_and_page_number(settings: Settings) -> None:
    if not shutil.which(settings.pdf_converter):
        pytest.skip("Real PDF conversion requires LibreOffice; run this test in the API image")
    params = gost_parameters()
    params.page_number_start = 7
    binary, _warnings = document_service.build_export(
        LexicalContent.model_validate(formatting_content()), params, {}, "pdf", settings
    )
    reader = PdfReader(BytesIO(binary))
    result = "\n".join(page.extract_text() for page in reader.pages)
    assert "Глава 1." in result and "Ячейка А" in result and "Ячейка Б" in result
    assert "3." in result and "4." in result
    assert "7" in reader.pages[0].extract_text()
