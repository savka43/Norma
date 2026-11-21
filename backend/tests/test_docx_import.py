import io
import json
import struct
import warnings
from pathlib import Path
from zipfile import ZipFile, ZipInfo

import pytest
from PIL import Image
from pydantic import ValidationError

from app.api_v1.documents import docx_import as importer
from app.api_v1.documents.lexical import LexicalContent, content_nodes
from app.api_v1.documents.schemas import DocumentSave
from tests.docx_helpers import docx, image_docx, paragraph


def test_paragraphs_headings_inherited_styles_inline_and_safe_text() -> None:
    source = docx(
        paragraph("Введение", '<w:pPr><w:pStyle w:val="Child"/></w:pPr>')
        + '<w:p><w:r><w:rPr><w:b/><w:i/><w:u w:val="single"/></w:rPr>'
        "<w:t>&lt;script&gt;literal&lt;/script&gt;</w:t><w:tab/><w:br/>"
        "<w:t>Новая строка</w:t></w:r></w:p>",
        extra={
            "word/styles.xml": (
                f'<w:styles xmlns:w="{importer.W[1:-1]}">'
                '<w:style w:styleId="Base"><w:pPr><w:outlineLvl w:val="1"/></w:pPr></w:style>'
                '<w:style w:styleId="Child"><w:basedOn w:val="Base"/></w:style></w:styles>'
            ).encode()
        },
    )
    result = importer.convert_docx(source)
    nodes = content_nodes(result.content.stored())
    assert any(n.get("type") == "heading" and n.get("tag") == "h2" for n in nodes)
    assert any(n.get("text") == "<script>literal</script>" and n.get("format") == 11 for n in nodes)
    assert any(n.get("type") == "linebreak" for n in nodes)
    assert result.warnings == {"formatting_normalized_to_template": 1}


def test_numbered_nested_lists_and_restart() -> None:
    def item(value: str, level: int, number: int = 1) -> str:
        return paragraph(
            value,
            "<w:pPr><w:numPr>" + f'<w:ilvl w:val="{level}"/>'
            f'<w:numId w:val="{number}"/></w:numPr></w:pPr>',
        )

    source = docx(
        item("Первый", 0)
        + item("Вложенный", 1)
        + item("Второй", 0)
        + paragraph("Разрыв")
        + item("Продолжение", 0)
        + item("Сначала", 0, 2),
        extra={
            "word/numbering.xml": (
                f'<w:numbering xmlns:w="{importer.W[1:-1]}">'
                '<w:abstractNum w:abstractNumId="1">'
                '<w:lvl w:ilvl="0"><w:start w:val="3"/><w:numFmt w:val="decimal"/></w:lvl>'
                '<w:lvl w:ilvl="1"><w:start w:val="1"/><w:numFmt w:val="bullet"/></w:lvl>'
                '</w:abstractNum><w:num w:numId="1"><w:abstractNumId w:val="1"/></w:num>'
                '<w:num w:numId="2"><w:abstractNumId w:val="1"/>'
                '<w:lvlOverride w:ilvl="0"><w:startOverride w:val="1"/></w:lvlOverride>'
                "</w:num></w:numbering>"
            ).encode()
        },
    )
    result = importer.convert_docx(source)
    nodes = content_nodes(result.content.stored())
    lists = [n for n in reversed(nodes) if n.get("type") == "list"]
    assert [n["start"] for n in lists if n["listType"] == "number"] == [3, 5, 1]
    assert any(n.get("listType") == "bullet" for n in lists)
    assert {str(n["text"]) for n in nodes if n.get("type") == "text"} == {
        "Первый",
        "Вложенный",
        "Второй",
        "Разрыв",
        "Продолжение",
        "Сначала",
    }


def test_table_cells_keep_order_and_warn_about_complex_features() -> None:
    nested = "<w:tbl><w:tr><w:tc>" + paragraph("Вложенная") + "</w:tc></w:tr></w:tbl>"
    source = docx(
        '<w:tbl><w:tr><w:tc><w:tcPr><w:gridSpan w:val="2"/>'
        '<w:vMerge w:val="restart"/></w:tcPr>'
        + paragraph("Ячейка")
        + nested
        + "</w:tc></w:tr></w:tbl>"
    )
    result = importer.convert_docx(source)
    nodes = list(reversed(content_nodes(result.content.stored())))
    assert [n["text"] for n in nodes if n.get("type") == "text"] == ["Ячейка", "Вложенная"]
    assert sum(n.get("type") == "table" for n in nodes) == 1
    assert any(n.get("colSpan") == 2 for n in nodes)
    assert "nested_table_flattened" in result.warnings
    assert "vertical_merge_normalized" in result.warnings


@pytest.mark.parametrize("image_format", ["PNG", "JPEG"])
def test_images_are_decoded_reencoded_and_referenced_by_uuid(image_format: str) -> None:
    result = importer.convert_docx(image_docx(image_format))
    assert len(result.assets) == 1
    asset = result.assets[0]
    assert asset.media_type == "image/png" and asset.width == 4 and asset.height == 3
    assert result.content.image_ids() == {asset.id}
    with Image.open(io.BytesIO(asset.data)) as image:
        assert image.format == "PNG"


def test_fields_formulas_and_external_links_are_reported_without_fetching() -> None:
    source = docx(
        '<w:p><w:hyperlink r:id="external"><w:r><w:t>Ссылка</w:t></w:r></w:hyperlink>'
        '<w:fldSimple w:instr="PAGE"><w:r><w:t>42</w:t></w:r></w:fldSimple>'
        '<m:oMath xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math">'
        '<m:r><m:t>x+y</m:t></m:r></m:oMath><w:r><w:footnoteReference w:id="1"/>'
        "</w:r></w:p>",
        extra={
            "word/_rels/document.xml.rels": (
                f'<Relationships xmlns="{importer.PKG[1:-1]}"><Relationship Id="external" '
                f'Type="{importer.R[1:-1]}/hyperlink" TargetMode="External" '
                'Target="http://127.0.0.1:1/private"/></Relationships>'
            ).encode(),
            "word/header1.xml": b"<header/>",
        },
    )
    result = importer.convert_docx(source)
    encoded = json.dumps(result.content.stored(), ensure_ascii=False)
    assert all(t in encoded for t in ("Ссылка", "42", "x+y"))
    assert {
        "unsupported_hyperlink",
        "unsupported_fldSimple",
        "unsupported_oMath",
        "unsupported_footnoteReference",
        "unsupported_part_header",
        "external_relationship_ignored",
    } <= result.warnings.keys()
    assert "http://" not in encoded


@pytest.mark.parametrize(
    "data",
    [
        b"",
        b"not zip",
        b"PK\x03\x04broken",
        docx(
            extra={
                "word/document.xml": b'<!DOCTYPE x [<!ENTITY e SYSTEM "file:///etc/passwd">]><x>&e;</x>'
            }
        ),
        docx(extra={"../escape": b"x"}),
        docx(extra={"/absolute": b"x"}),
        docx(extra={"word\\escape": b"x"}),
        docx(extra={"word/bad.xml": b"<broken>"}),
    ],
)
def test_rejects_invalid_zip_paths_xml_and_dtd(data: bytes) -> None:
    with pytest.raises(importer.InvalidDocx):
        importer.convert_docx(data)


def test_duplicate_encrypted_symlink_and_bad_crc_entries_are_rejected() -> None:
    output = io.BytesIO(docx())
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        with ZipFile(output, "a") as archive:
            archive.writestr("word/document.xml", b"duplicate")
    with pytest.raises(importer.InvalidDocx):
        importer.convert_docx(output.getvalue())
    output = io.BytesIO(docx())
    with ZipFile(output, "a") as archive:
        info = ZipInfo("word/link")
        info.external_attr = 0o120777 << 16
        archive.writestr(info, "target")
    with pytest.raises(importer.InvalidDocx):
        importer.convert_docx(output.getvalue())
    data = bytearray(docx())
    central = data.index(b"PK\x01\x02")
    struct.pack_into("<H", data, central + 8, 1)
    with pytest.raises(importer.InvalidDocx):
        importer.convert_docx(bytes(data))
    data = bytearray(docx())
    data[30 + len("[Content_Types].xml") + 10] ^= 255
    with pytest.raises(importer.InvalidDocx):
        importer.convert_docx(bytes(data))


@pytest.mark.parametrize(
    "limit,value",
    [
        ("MAX_UPLOAD_BYTES", 100),
        ("MAX_ENTRIES", 2),
        ("MAX_UNPACKED_BYTES", 100),
        ("MAX_PART_BYTES", 100),
        ("MAX_XML_NODES", 2),
        ("MAX_IMAGE_PIXELS", 1),
    ],
)
def test_resource_limits(limit: str, value: int, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(importer, limit, value)
    with pytest.raises(importer.InvalidDocx):
        importer.convert_docx(image_docx())


def test_schema_v1_cannot_claim_v2_nodes() -> None:
    data = importer.convert_docx(image_docx()).content.stored()
    payload = {
        "content": data,
        "schema_version": 1,
        "expected_revision": 1,
        "template_version_id": "00000000-0000-0000-0000-000000000001",
    }
    with pytest.raises(ValidationError, match="require schema_version 2"):
        DocumentSave.model_validate(payload)
    assert DocumentSave.model_validate({**payload, "schema_version": 2}).content.stored() == data


def test_real_lexical_table_fixture_round_trip() -> None:
    fixture = Path(__file__).parent / "fixtures/lexical-table-0.53.0.json"
    if not fixture.exists():
        pytest.fail("Generate and commit the real Lexical table fixture")
    data = json.loads(fixture.read_text())
    assert LexicalContent.model_validate(data).stored() == data


def test_docx_created_by_real_library_imports_in_order() -> None:
    source = (Path(__file__).parent / "fixtures/synthetic-import.docx").read_bytes()
    result = importer.convert_docx(source)
    nodes = list(reversed(content_nodes(result.content.stored())))
    texts = [n["text"] for n in nodes if n.get("type") == "text"]
    assert texts == [
        "Синтетическая ВКР",
        "Обычный текст; ",
        "полужирный",
        " и курсив",
        "Маркированный пункт",
        "Нумерованный пункт",
        "Ячейка 1",
        "Ячейка 2",
        "Ячейка 3",
        "Ячейка 4",
        "Конец документа",
    ]
    assert any(n.get("type") == "heading" and n.get("tag") == "h1" for n in nodes)
    assert {str(n["listType"]) for n in nodes if n.get("type") == "list"} == {"bullet", "number"}
    assert len(result.assets) == 1
    assert "unsupported_part_header" in result.warnings


def test_complexity_compression_macros_and_style_cycles_are_rejected() -> None:
    sources = [
        docx(paragraph("x" * 100_000)),
        docx(extra={"word/deep.xml": ("<x>" * 65 + "</x>" * 65).encode()}),
        docx(
            extra={
                "[Content_Types].xml": (
                    f'<Types xmlns="{importer.CT[1:-1]}"><Override PartName="/word/document.xml" '
                    'ContentType="application/vnd.ms-word.document.macroEnabled.main+xml"/></Types>'
                ).encode()
            }
        ),
        docx(
            paragraph("Cycle", '<w:pPr><w:pStyle w:val="A"/></w:pPr>'),
            extra={
                "word/styles.xml": (
                    f'<w:styles xmlns:w="{importer.W[1:-1]}">'
                    '<w:style w:styleId="A"><w:basedOn w:val="B"/></w:style>'
                    '<w:style w:styleId="B"><w:basedOn w:val="A"/></w:style></w:styles>'
                ).encode(),
            },
        ),
    ]
    for source in sources:
        with pytest.raises(importer.InvalidDocx):
            importer.convert_docx(source)


def test_irregular_table_is_padded_without_losing_text() -> None:
    source = docx(
        "<w:tbl><w:tr><w:tc>" + paragraph("A") + "</w:tc></w:tr>"
        "<w:tr><w:tc>"
        + paragraph("B")
        + "</w:tc><w:tc>"
        + paragraph("C")
        + "</w:tc></w:tr></w:tbl>"
    )
    result = importer.convert_docx(source)
    assert "irregular_table_normalized" in result.warnings
    assert {
        str(n["text"]) for n in content_nodes(result.content.stored()) if n.get("type") == "text"
    } == {"A", "B", "C"}
