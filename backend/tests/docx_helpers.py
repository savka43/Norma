import io
from zipfile import ZIP_DEFLATED, ZipFile

from PIL import Image

from app.api_v1.documents.docx_import import CT, PKG, R, W


def docx(body: str = "", *, extra: dict[str, bytes] | None = None) -> bytes:
    parts = {
        "[Content_Types].xml": (
            f'<Types xmlns="{CT[1:-1]}">'
            '<Default Extension="rels" '
            'ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/word/document.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
            "</Types>"
        ).encode(),
        "_rels/.rels": (
            f'<Relationships xmlns="{PKG[1:-1]}">'
            f'<Relationship Id="rId1" Type="{R[1:-1]}/officeDocument" '
            'Target="word/document.xml"/></Relationships>'
        ).encode(),
        "word/document.xml": (
            f'<w:document xmlns:w="{W[1:-1]}" xmlns:r="{R[1:-1]}" '
            'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
            f"<w:body>{body}</w:body></w:document>"
        ).encode(),
        **(extra or {}),
    }
    output = io.BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        for name, value in parts.items():
            archive.writestr(name, value)
    return output.getvalue()


def paragraph(value: str, properties: str = "") -> str:
    return f"<w:p>{properties}<w:r><w:t>{value}</w:t></w:r></w:p>"


def image_docx(image_format: str = "PNG") -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (4, 3), color="red").save(output, format=image_format)
    return docx(
        paragraph("До рисунка") + '<w:p><w:r><w:drawing><a:blip r:embed="pic1"/>'
        "</w:drawing></w:r></w:p>" + paragraph("После рисунка"),
        extra={
            "word/media/image.bin": output.getvalue(),
            "word/_rels/document.xml.rels": (
                f'<Relationships xmlns="{PKG[1:-1]}"><Relationship Id="pic1" '
                f'Type="{R[1:-1]}/image" Target="media/image.bin"/></Relationships>'
            ).encode(),
        },
    )
