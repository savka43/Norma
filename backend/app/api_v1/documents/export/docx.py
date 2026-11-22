# python-docx exposes generated OOXML methods and private XML handles as its
# documented escape hatch. Keep incomplete third-party typing inside this adapter.
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportPrivateUsage=false
from copy import deepcopy
from dataclasses import dataclass
from io import BytesIO
from typing import cast
from uuid import UUID

from docx import Document as new_document
from docx.document import Document
from docx.enum.section import WD_ORIENT
from docx.enum.style import WD_STYLE_TYPE
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Mm, Pt, RGBColor
from docx.styles.style import ParagraphStyle
from docx.table import _Cell
from docx.text.paragraph import Paragraph

from app.api_v1.documents.lexical import (
    BlockNode,
    CaptionNode,
    HeadingNode,
    ImageNode,
    LexicalContent,
    LineBreakNode,
    ListNode,
    TableNode,
    TextNode,
)
from app.api_v1.formatting.schemas import TemplateParameters, TextStyle

DOCX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


class UnsupportedExport(ValueError):
    pass


@dataclass(frozen=True)
class ImageAsset:
    data: bytes
    width: int
    height: int


def set_style(style: ParagraphStyle, spec: TextStyle) -> None:
    style.font.name = spec.font_family
    style.font.size = Pt(spec.font_size_pt)
    style.font.bold, style.font.italic = spec.bold, spec.italic
    style.font.color.rgb = RGBColor(0, 0, 0)
    rpr = style.element.get_or_add_rPr()
    fonts = rpr.find(qn("w:rFonts"))
    assert fonts is not None
    for name in ("ascii", "hAnsi", "eastAsia", "cs"):
        fonts.set(qn(f"w:{name}"), spec.font_family)
    fmt = style.paragraph_format
    fmt.line_spacing = spec.line_spacing
    fmt.first_line_indent = Mm(spec.first_line_indent_mm)
    fmt.space_before, fmt.space_after = Pt(spec.space_before_pt), Pt(spec.space_after_pt)
    fmt.widow_control = True
    fmt.alignment = {
        "left": WD_ALIGN_PARAGRAPH.LEFT,
        "right": WD_ALIGN_PARAGRAPH.RIGHT,
        "center": WD_ALIGN_PARAGRAPH.CENTER,
        "justify": WD_ALIGN_PARAGRAPH.JUSTIFY,
    }[spec.alignment]


class Writer:
    def __init__(self, parameters: TemplateParameters, assets: dict[UUID, ImageAsset]) -> None:
        self.parameters, self.assets = parameters, assets
        self.document = new_document()
        self.usable_width = (
            (210 if parameters.orientation == "portrait" else 297)
            - parameters.margins.left_mm
            - parameters.margins.right_mm
        )
        self.usable_height = (
            (297 if parameters.orientation == "portrait" else 210)
            - parameters.margins.top_mm
            - parameters.margins.bottom_mm
        )
        section = self.document.sections[0]
        section.orientation = (
            WD_ORIENT.PORTRAIT if parameters.orientation == "portrait" else WD_ORIENT.LANDSCAPE
        )
        section.page_width = Mm(210 if parameters.orientation == "portrait" else 297)
        section.page_height = Mm(297 if parameters.orientation == "portrait" else 210)
        section.top_margin, section.bottom_margin = (
            Mm(parameters.margins.top_mm),
            Mm(parameters.margins.bottom_mm),
        )
        section.left_margin, section.right_margin = (
            Mm(parameters.margins.left_mm),
            Mm(parameters.margins.right_mm),
        )
        section.footer_distance = Mm(min(10, parameters.margins.bottom_mm / 2))
        styles: list[tuple[str, TextStyle]] = [
            ("Normal", parameters.body),
            ("Norma Table Caption", parameters.caption),
            ("Norma Figure Caption", parameters.caption),
            ("Norma Image", parameters.caption),
            ("Norma List", parameters.list),
            ("Norma Table", parameters.table),
        ] + [(f"Heading {i + 1}", style) for i, style in enumerate(parameters.headings)]
        for name, spec in styles:
            if name not in self.document.styles:
                self.document.styles.add_style(name, WD_STYLE_TYPE.PARAGRAPH)
            style = cast(ParagraphStyle, self.document.styles[name])
            set_style(style, spec)
            if name.startswith("Heading"):
                style.paragraph_format.keep_with_next = True
        page_number = OxmlElement("w:pgNumType")
        page_number.set(qn("w:start"), str(parameters.page_number_start))
        section._sectPr.append(page_number)
        footer = section.footer.paragraphs[0]
        footer.alignment = WD_ALIGN_PARAGRAPH.CENTER
        footer.paragraph_format.first_line_indent = Mm(0)
        footer.paragraph_format.space_before = Pt(0)
        footer.paragraph_format.space_after = Pt(0)
        footer.paragraph_format.line_spacing = 1
        run = footer.add_run()
        run.font.name = parameters.body.font_family
        run.font.size = Pt(parameters.body.font_size_pt)
        field = OxmlElement("w:fldSimple")
        field.set(qn("w:instr"), "PAGE")
        run._r.addnext(field)
        # Scrub python-docx's template metadata.
        props = self.document.core_properties
        props.author, props.last_modified_by, props.comments = "", "", ""
        props.title, props.subject, props.keywords = "", "", ""

    def inline(
        self,
        paragraph: Paragraph,
        nodes: list[TextNode | LineBreakNode | ImageNode | ListNode],
        width: float,
    ) -> None:
        for node in nodes:
            if isinstance(node, TextNode):
                run = paragraph.add_run(node.text)
                flags = node.format
                # False would override template bold/italic; None inherits it.
                run.bold = True if flags & 1 else None
                run.italic = True if flags & 2 else None
                run.font.strike = bool(flags & 4)
                run.underline = bool(flags & 8)
                run.font.subscript = bool(flags & 32)
                run.font.superscript = bool(flags & 64)
            elif isinstance(node, LineBreakNode):
                paragraph.add_run().add_break()
            elif isinstance(node, ImageNode):
                asset = self.assets[node.asset_id]
                ratio = min(
                    width / (asset.width * 25.4 / 96),
                    self.usable_height * 0.8 / (asset.height * 25.4 / 96),
                    1,
                )
                picture = paragraph.add_run().add_picture(
                    BytesIO(asset.data), width=Mm(asset.width * 25.4 / 96 * ratio)
                )
                picture._inline.docPr.set("descr", node.alt_text)
                for distance in ("distL", "distR", "distT", "distB"):
                    picture._inline.set(distance, "0")
            # Nested lists are emitted by blocks(), outside this paragraph.

    def numbering(self, paragraph: Paragraph, node: ListNode, level: int) -> None:
        # A separate numId per list retains starts and independent restarts.
        numbering = self.document.part.numbering_part.element
        abstract_id = (
            max(
                [
                    int(cast(str, e.get(qn("w:abstractNumId"), "0")))
                    for e in numbering.findall(qn("w:abstractNum"))
                ]
                + [0]
            )
            + 1
        )
        num_id = (
            max(
                [int(cast(str, e.get(qn("w:numId"), "0"))) for e in numbering.findall(qn("w:num"))]
                + [0]
            )
            + 1
        )
        abstract = OxmlElement("w:abstractNum")
        abstract.set(qn("w:abstractNumId"), str(abstract_id))
        lvl = OxmlElement("w:lvl")
        lvl.set(qn("w:ilvl"), str(level))
        for name, value in (
            ("start", str(node.start)),
            ("numFmt", "decimal" if node.listType == "number" else "bullet"),
            ("lvlText", f"%{level + 1}." if node.listType == "number" else "•"),
        ):
            child = OxmlElement(f"w:{name}")
            child.set(qn("w:val"), value)
            lvl.append(child)
        abstract.append(lvl)
        numbering.append(abstract)
        num = OxmlElement("w:num")
        num.set(qn("w:numId"), str(num_id))
        ref = OxmlElement("w:abstractNumId")
        ref.set(qn("w:val"), str(abstract_id))
        num.append(ref)
        numbering.append(num)
        props = paragraph._p.get_or_add_pPr().get_or_add_numPr()
        props.get_or_add_ilvl().val = level
        props.get_or_add_numId().val = num_id
        paragraph.paragraph_format.left_indent = Mm(
            level * self.parameters.list.first_line_indent_mm
        )

    def blocks(
        self,
        nodes: list[BlockNode],
        container: Document | _Cell,
        width: float,
        *,
        in_table: bool = False,
        level: int = 0,
    ) -> None:
        if level > 8:
            raise UnsupportedExport("DOCX export supports at most nine nested list levels")
        for node in nodes:
            if isinstance(node, TableNode):
                self.table(node, container, width)
            elif isinstance(node, ListNode):
                first: Paragraph | None = None
                for item in node.children:
                    inline = [n for n in item.children if not isinstance(n, ListNode)]
                    if inline or not item.children:
                        paragraph = container.add_paragraph(style="Norma List")
                        self.inline(
                            paragraph,
                            list(inline),
                            max(1, width - (level + 1) * self.parameters.list.first_line_indent_mm),
                        )
                        if first is None:
                            self.numbering(paragraph, node, level)
                            first = paragraph
                        else:
                            paragraph._p.get_or_add_pPr().append(
                                deepcopy(first._p.get_or_add_pPr().numPr)
                            )
                            paragraph.paragraph_format.left_indent = (
                                first.paragraph_format.left_indent
                            )
                            paragraph.paragraph_format.first_line_indent = (
                                first.paragraph_format.first_line_indent
                            )
                    for nested in item.children:
                        if isinstance(nested, ListNode):
                            self.blocks(
                                [nested], container, width, in_table=in_table, level=level + 1
                            )
            else:
                image_only = bool(node.children) and all(
                    isinstance(child, ImageNode) for child in node.children
                )
                if isinstance(node, CaptionNode) and node.kind == "figure" and container.paragraphs:
                    container.paragraphs[-1].paragraph_format.keep_with_next = True
                name = (
                    f"Heading {node.tag[1:]}"
                    if isinstance(node, HeadingNode)
                    else f"Norma {node.kind.title()} Caption"
                    if isinstance(node, CaptionNode)
                    else "Norma Image"
                    if image_only
                    else "Norma Table"
                    if in_table
                    else "Normal"
                )
                paragraph = container.add_paragraph(style=name)
                if node.direction == "rtl":
                    paragraph._p.get_or_add_pPr().append(OxmlElement("w:bidi"))
                if isinstance(node, CaptionNode):
                    paragraph.paragraph_format.keep_with_next = node.kind == "table"
                    paragraph.paragraph_format.keep_together = True
                spec = (
                    self.parameters.headings[int(node.tag[1:]) - 1]
                    if isinstance(node, HeadingNode)
                    else self.parameters.caption
                    if isinstance(node, CaptionNode) or image_only
                    else self.parameters.table
                    if in_table
                    else self.parameters.body
                )
                self.inline(
                    paragraph, list(node.children), max(1, width - spec.first_line_indent_mm)
                )

    def table(self, node: TableNode, container: Document | _Cell, width: float) -> None:
        count = sum(cell.colSpan for cell in node.children[0].children)
        table = container.add_table(rows=0, cols=count)
        table.autofit = False
        table.alignment = WD_TABLE_ALIGNMENT.LEFT
        indent = OxmlElement("w:tblInd")
        indent.set(qn("w:w"), "0")
        indent.set(qn("w:type"), "dxa")
        table._tbl.tblPr.append(indent)
        for column in table.columns:
            column.width = Mm(width / count)
        table.style = "Table Grid"
        for source in node.children:
            row = table.add_row()
            if all(cell.headerState & 1 for cell in source.children):
                row._tr.get_or_add_trPr().append(OxmlElement("w:tblHeader"))
            index = 0
            for cell_node in source.children:
                cell = row.cells[index]
                if cell_node.colSpan > 1:
                    cell = cell.merge(row.cells[index + cell_node.colSpan - 1])
                cell.width = Mm(width / count * cell_node.colSpan)
                placeholder = cell.paragraphs[0]._p
                self.blocks(
                    list(cell_node.children),
                    cell,
                    max(1, width / count * cell_node.colSpan - 4),
                    in_table=True,
                )
                placeholder.getparent().remove(placeholder)
                # Word requires a trailing paragraph even when the final block is a table.
                if not cell.paragraphs:
                    cell.add_paragraph(style="Norma Table")
                index += cell_node.colSpan


def render_docx(
    content: LexicalContent, parameters: TemplateParameters, assets: dict[UUID, ImageAsset]
) -> bytes:
    writer = Writer(parameters, assets)
    writer.blocks(content.root.children, writer.document, writer.usable_width)
    output = BytesIO()
    writer.document.save(output)
    return output.getvalue()
