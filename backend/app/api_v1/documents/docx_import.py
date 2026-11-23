"""Bounded OOXML import. Never extracts paths, executes HTML or follows links."""

from __future__ import annotations

import io
import posixpath
import zipfile
import zlib
from dataclasses import dataclass, field
from typing import cast
from uuid import UUID, uuid4
from xml.etree.ElementTree import Element, ParseError

from defusedxml.common import DefusedXmlException
from defusedxml.ElementTree import iterparse
from pydantic import JsonValue, ValidationError

from app.api_v1.documents.images import (
    MAX_IMAGE_PIXELS,
    ImageLimitExceeded,
    InvalidImage,
    normalize_image,
)
from app.api_v1.documents.lexical import LexicalContent

DOCX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_UNPACKED_BYTES = 50 * 1024 * 1024
MAX_PART_BYTES = 8 * 1024 * 1024
MAX_ENTRIES = 1000
MAX_XML_NODES = 100_000
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
PKG = "{http://schemas.openxmlformats.org/package/2006/relationships}"
CT = "{http://schemas.openxmlformats.org/package/2006/content-types}"


class InvalidDocx(ValueError):
    pass


@dataclass(frozen=True)
class ImportedAsset:
    id: UUID
    data: bytes
    media_type: str
    width: int
    height: int


@dataclass
class ImportResult:
    content: LexicalContent
    warnings: dict[str, int]
    assets: list[ImportedAsset]


def element(kind: str, children: list[JsonValue] | None = None) -> dict[str, JsonValue]:
    return {
        "type": kind,
        "version": 1,
        "direction": None,
        "format": "",
        "indent": 0,
        "children": children if children is not None else [],
    }


def text(value: str, formatting: int = 0) -> dict[str, JsonValue]:
    return {
        "type": "text",
        "version": 1,
        "text": value,
        "format": formatting,
        "detail": 0,
        "mode": "normal",
        "style": "",
    }


def integer(value: str | None, default: int, maximum: int = 2**31 - 1) -> int:
    try:
        result = int(value) if value is not None else default
    except ValueError as exc:
        raise InvalidDocx("Invalid numeric OOXML property") from exc
    if result < 0 or result > maximum:
        raise InvalidDocx("OOXML numeric property is out of range")
    return result


def val(parent: Element | None, path: str) -> str | None:
    item = parent.find(path) if parent is not None else None
    return item.get(W + "val") if item is not None else None


def read_package(data: bytes) -> tuple[dict[str, bytes], dict[str, Element]]:
    if not data or len(data) > MAX_UPLOAD_BYTES:
        raise InvalidDocx("DOCX size limit exceeded or file is empty")
    parts: dict[str, bytes] = {}
    xml: dict[str, Element] = {}
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            entries = archive.infolist()
            if len(entries) > MAX_ENTRIES:
                raise InvalidDocx("Too many DOCX ZIP entries")
            total = nodes = 0
            names: set[str] = set()
            for entry in entries:
                name = entry.filename
                if (
                    not name
                    or "\\" in name
                    or "\x00" in entry.orig_filename
                    or name.startswith("/")
                    or ":" in name
                    or any(part in (".", "..", "") for part in name.rstrip("/").split("/"))
                    or name in names
                    or (entry.external_attr >> 16) & 0o170000 == 0o120000
                    or entry.flag_bits & 1
                    or entry.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED)
                ):
                    raise InvalidDocx("Unsafe DOCX ZIP entry")
                names.add(name)
                if entry.is_dir():
                    continue
                total += entry.file_size
                if (
                    entry.file_size > MAX_PART_BYTES
                    or total > MAX_UNPACKED_BYTES
                    or entry.file_size > max(entry.compress_size, 1) * 200
                ):
                    raise InvalidDocx("DOCX decompression limit exceeded")
                with archive.open(entry) as stream:
                    content = stream.read(MAX_PART_BYTES + 1)
                if len(content) != entry.file_size or len(content) > MAX_PART_BYTES:
                    raise InvalidDocx("Invalid DOCX entry size")
                parts[name] = content
                if name.endswith((".xml", ".rels")):
                    events = iterparse(
                        io.BytesIO(content), events=("start", "end"), forbid_dtd=True
                    )
                    depth = 0
                    root: Element | None = None
                    for event, node in events:
                        if event == "start":
                            if root is None:
                                root = cast(Element, node)
                            depth += 1
                            nodes += 1
                            if depth > 64 or nodes > MAX_XML_NODES:
                                raise InvalidDocx("DOCX XML complexity limit exceeded")
                        else:
                            depth -= 1
                    if root is None:
                        raise InvalidDocx("Empty XML part")
                    xml[name] = root
    except (
        zipfile.BadZipFile,
        RuntimeError,
        NotImplementedError,
        EOFError,
        ParseError,
        DefusedXmlException,
        zlib.error,
        LookupError,
    ) as exc:
        raise InvalidDocx("Invalid or unsafe DOCX package") from exc
    types = xml.get("[Content_Types].xml")
    rels = xml.get("_rels/.rels")
    document = xml.get("word/document.xml")
    if types is None or rels is None or document is None or document.tag != W + "document":
        raise InvalidDocx("A Word DOCX document package is required")
    if types.tag != CT + "Types" or rels.tag != PKG + "Relationships":
        raise InvalidDocx("Invalid DOCX package metadata")
    if any(
        "macroenabled" in node.get("ContentType", "").lower()
        or "vbaproject" in node.get("ContentType", "").lower()
        for node in types
    ):
        raise InvalidDocx("Macro-enabled files are not supported")
    if not any(
        node.get("PartName") == "/word/document.xml"
        and node.get("ContentType") == DOCX_MEDIA_TYPE + ".main+xml"
        for node in types
    ):
        raise InvalidDocx("The main part must be a DOCX document")
    if not any(
        node.get("Type") == R[1:-1] + "/officeDocument"
        and node.get("Target") in ("word/document.xml", "/word/document.xml")
        and node.get("TargetMode") != "External"
        for node in rels
    ):
        raise InvalidDocx("Invalid DOCX main-part relationship")
    return parts, xml


@dataclass
class Converter:
    parts: dict[str, bytes]
    xml: dict[str, Element]
    warnings: dict[str, int] = field(default_factory=dict)
    assets: dict[str, ImportedAsset] = field(default_factory=dict)
    asset_bytes: int = 0
    list_counts: dict[str, dict[int, int]] = field(default_factory=dict)
    styles: dict[str | None, Element] = field(init=False)
    numbers: dict[str | None, Element] = field(init=False)
    abstract_numbers: dict[str | None, Element] = field(init=False)
    relationships: dict[str | None, Element] = field(init=False)
    style_cache: dict[str, list[Element]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        def lookup(part: str, tag: str, attribute: str) -> dict[str | None, Element]:
            root = self.xml.get(part)
            if root is None:
                return {}
            return {node.get(attribute): node for node in root.findall(tag)}

        self.styles = lookup("word/styles.xml", W + "style", W + "styleId")
        self.numbers = lookup("word/numbering.xml", W + "num", W + "numId")
        self.abstract_numbers = lookup("word/numbering.xml", W + "abstractNum", W + "abstractNumId")
        self.relationships = lookup("word/_rels/document.xml.rels", PKG + "Relationship", "Id")

    def warn(self, code: str) -> None:
        self.warnings[code] = self.warnings.get(code, 0) + 1

    def style_chain(self, style_id: str | None) -> list[Element]:
        if style_id is None:
            return []
        original_id = style_id
        if original_id in self.style_cache:
            return self.style_cache[original_id]
        chain: list[Element] = []
        seen: set[str] = set()
        while style_id is not None:
            if style_id in seen or len(seen) >= 32:
                raise InvalidDocx("Cyclic or too deep DOCX style inheritance")
            seen.add(style_id)
            style = self.styles.get(style_id)
            if style is None:
                self.warn("unknown_style")
                break
            chain.append(style)
            style_id = val(style, W + "basedOn")
        self.style_cache[original_id] = list(reversed(chain))
        return self.style_cache[original_id]

    def paragraph_properties(self, paragraph: Element) -> dict[str, str]:
        result: dict[str, str] = {}
        properties = paragraph.find(W + "pPr")
        if properties is not None and properties.find(W + "sectPr") is not None:
            self.warn("section_break_normalized")
        if properties is not None and properties.find(W + "pageBreakBefore") is not None:
            self.warn("page_break_normalized")
        chain = self.style_chain(val(properties, W + "pStyle"))
        for style in chain:
            caption = {"Norma Table Caption": "table", "Norma Figure Caption": "figure"}.get(
                val(style, W + "name") or ""
            )
            if caption:
                result["caption"] = caption
        for source in [*(s.find(W + "pPr") for s in chain), properties]:
            for key, path in (
                ("outline", W + "outlineLvl"),
                ("num", W + "numPr/" + W + "numId"),
                ("level", W + "numPr/" + W + "ilvl"),
            ):
                value = val(source, path)
                if value is not None:
                    result[key] = value
        return result

    def run_format(self, run: Element, paragraph: Element) -> int:
        sources: list[Element | None] = []
        for style in self.style_chain(val(paragraph.find(W + "pPr"), W + "pStyle")):
            sources.append(style.find(W + "rPr"))
        properties = run.find(W + "rPr")
        sources.extend(
            style.find(W + "rPr") for style in self.style_chain(val(properties, W + "rStyle"))
        )
        sources.append(properties)
        formatting = 0
        for source in sources:
            if source is None:
                continue
            for tag, flag in (("b", 1), ("i", 2), ("strike", 4), ("u", 8)):
                item = source.find(W + tag)
                if item is not None:
                    if item.get(W + "val") in ("0", "false", "off", "none"):
                        formatting &= ~flag
                    else:
                        formatting |= flag
            vertical = val(source, W + "vertAlign")
            if vertical is not None:
                formatting &= ~(32 | 64)
                formatting |= {"subscript": 32, "superscript": 64}.get(vertical, 0)
        return formatting

    def image(self, drawing: Element) -> list[JsonValue]:
        images: list[JsonValue] = []
        for blip in drawing.iter(A + "blip"):
            rid = blip.get(R + "embed")
            rel = self.relationships.get(rid) if rid is not None else None
            if (
                rel is None
                or rel.get("TargetMode") == "External"
                or rel.get("Type") != R[1:-1] + "/image"
            ):
                self.warn("unsupported_image")
                continue
            target = rel.get("Target", "")
            path = posixpath.normpath(posixpath.join("word", target))
            if target.startswith("/"):
                path = target.lstrip("/")
            if path not in self.parts or not path.startswith("word/media/"):
                self.warn("unsupported_image")
                continue
            asset = self.assets.get(path)
            if asset is None:
                try:
                    image = normalize_image(self.parts[path], pixel_limit=MAX_IMAGE_PIXELS)
                except ImageLimitExceeded as exc:
                    raise InvalidDocx(str(exc)) from exc
                except InvalidImage:
                    self.warn("unsupported_image")
                    continue
                self.asset_bytes += len(image.data)
                if self.asset_bytes > MAX_UPLOAD_BYTES:
                    raise InvalidDocx("Decoded image size limit exceeded")
                asset = ImportedAsset(uuid4(), image.data, "image/png", image.width, image.height)
                self.assets[path] = asset
            alt = next(
                (n.get("descr", "") for n in drawing.iter() if n.tag.endswith("}docPr")), ""
            )[:2000]
            images.append(
                {"type": "norma-image", "version": 1, "asset_id": str(asset.id), "alt_text": alt}
            )
            self.warn("image_layout_normalized")
        if not images:
            self.warn("drawing_not_imported")
        return images

    def inline(self, source: Element, paragraph: Element, formatting: int = 0) -> list[JsonValue]:
        result: list[JsonValue] = []
        for child in source:
            local = child.tag.rsplit("}", 1)[-1]
            if child.tag in (W + "t", W + "delText") or local == "t":
                if child.text:
                    result.append(text(child.text, formatting))
            elif child.tag == W + "r":
                result.extend(self.inline(child, paragraph, self.run_format(child, paragraph)))
            elif child.tag in (W + "br", W + "cr"):
                result.append({"type": "linebreak", "version": 1})
                if child.get(W + "type") in ("page", "column"):
                    self.warn("page_break_normalized")
            elif child.tag == W + "tab":
                result.append(text("\t", formatting))
            elif child.tag == W + "drawing":
                result.extend(self.image(child))
            elif local in (
                "rPr",
                "pPr",
                "bookmarkStart",
                "bookmarkEnd",
                "proofErr",
                "lastRenderedPageBreak",
            ):
                continue
            else:
                if local in (
                    "hyperlink",
                    "fldSimple",
                    "fldChar",
                    "instrText",
                    "footnoteReference",
                    "endnoteReference",
                    "oMath",
                    "oMathPara",
                    "pict",
                    "object",
                    "ins",
                    "del",
                    "sdt",
                    "commentRangeStart",
                    "commentRangeEnd",
                    "commentReference",
                ):
                    self.warn("unsupported_" + local)
                elif len(child) or child.text:
                    self.warn("unsupported_inline")
                result.extend(self.inline(child, paragraph, formatting))
        return result

    def numbering(self, number_id: str, level: int) -> tuple[str, int]:
        numbering = self.xml.get("word/numbering.xml")
        if numbering is None:
            self.warn("unknown_numbering")
            return "number", 1
        number = self.numbers.get(number_id)
        abstract_id = val(number, W + "abstractNumId")
        abstract = self.abstract_numbers.get(abstract_id)
        definition = (
            next((n for n in abstract.findall(W + "lvl") if n.get(W + "ilvl") == str(level)), None)
            if abstract is not None
            else None
        )
        overrides = number.findall(W + "lvlOverride") if number is not None else []
        override = next((n for n in overrides if n.get(W + "ilvl") == str(level)), None)
        if override is not None and override.find(W + "lvl") is not None:
            definition = override.find(W + "lvl")
        kind = val(definition, W + "numFmt")
        if kind not in ("bullet", "decimal"):
            self.warn("numbering_format_normalized")
        start = integer(val(override, W + "startOverride") or val(definition, W + "start"), 1)
        return ("bullet" if kind == "bullet" else "number"), max(start, 1)

    def blocks(self, source: Element, *, in_table: bool = False) -> list[JsonValue]:
        result: list[JsonValue] = []
        lists: list[tuple[str, dict[str, JsonValue], list[JsonValue]]] = []
        for child in source:
            if child.tag == W + "p":
                props = self.paragraph_properties(child)
                inline = self.inline(child, child)
                num_id = props.get("num", "0")
                if num_id != "0":
                    level = integer(props.get("level"), 0, 8)
                    if level > len(lists):
                        self.warn("list_depth_normalized")
                        level = len(lists)
                    if level < len(lists) and lists[level][0] != num_id:
                        lists = lists[:level]
                    lists = lists[: level + 1]
                    kind, start = self.numbering(num_id, level)
                    counts = self.list_counts.setdefault(num_id, {})
                    value = counts.get(level, start)
                    counts[level] = value + 1
                    for other in list(counts):
                        if other > level:
                            del counts[other]
                    if level >= len(lists):
                        children: list[JsonValue] = []
                        node = element("list", children)
                        node.update(
                            {
                                "listType": kind,
                                "tag": "ul" if kind == "bullet" else "ol",
                                "start": value,
                            }
                        )
                        if level == 0:
                            result.append(node)
                        else:
                            parent_items = lists[-1][2]
                            # Lexical uses a separate list item to wrap a nested list.
                            parent_items.append({**element("listitem", [node]), "value": value})
                        lists.append((num_id, node, children))
                    lists[level][2].append({**element("listitem", inline), "value": value})
                else:
                    lists = []
                    outline = integer(props.get("outline"), 9, 9)
                    node = element("heading" if outline < 6 else "paragraph", inline)
                    if outline < 6:
                        node["tag"] = "h" + str(outline + 1)
                    elif "caption" in props:
                        node["type"], node["kind"] = "norma-caption", props["caption"]
                    elif outline < 9:
                        self.warn("heading_level_normalized")
                    result.append(node)
            elif child.tag == W + "tbl":
                lists = []
                if in_table:
                    self.warn("nested_table_flattened")
                    for row in child.findall(W + "tr"):
                        for cell in row.findall(W + "tc"):
                            result.extend(self.blocks(cell, in_table=True))
                else:
                    result.append(self.table(child))
            elif child.tag == W + "sectPr":
                if child.find(W + "type") is not None:
                    self.warn("section_break_normalized")
            elif child.tag not in (W + "tcPr", W + "tblPr", W + "tblGrid", W + "trPr"):
                self.warn("unsupported_block")
                result.extend(self.blocks(child, in_table=in_table))
                lists = []
        return result

    def table(self, source: Element) -> dict[str, JsonValue]:
        rows: list[JsonValue] = []
        cell_rows: list[tuple[int, list[JsonValue]]] = []
        for row in source.findall(W + "tr"):
            cells: list[JsonValue] = []
            width = 0
            for cell in row.findall(W + "tc"):
                span = max(integer(val(cell, W + "tcPr/" + W + "gridSpan"), 1, 100), 1)
                width += span
                if width > 100:
                    raise InvalidDocx("DOCX table exceeds 100 columns")
                if cell.find(W + "tcPr/" + W + "vMerge") is not None:
                    self.warn("vertical_merge_normalized")
                children = self.blocks(cell, in_table=True) or [element("paragraph")]
                cells.append(
                    {
                        **element("tablecell", children),
                        "headerState": 0,
                        "colSpan": span,
                        "rowSpan": 1,
                        "backgroundColor": None,
                    }
                )
            if cells:
                rows.append(element("tablerow", cells))
                cell_rows.append((width, cells))
        if not rows:
            raise InvalidDocx("DOCX table contains no cells")
        max_width = max(width for width, _ in cell_rows)
        for width, cells in cell_rows:
            if width != max_width:
                self.warn("irregular_table_normalized")
                cells.append(
                    {
                        **element("tablecell", [element("paragraph")]),
                        "headerState": 0,
                        "colSpan": max_width - width,
                        "rowSpan": 1,
                        "backgroundColor": None,
                    }
                )
        return element("table", rows)


def convert_docx(data: bytes) -> ImportResult:
    parts, xml = read_package(data)
    converter = Converter(parts, xml)
    body = xml["word/document.xml"].find(W + "body")
    if body is None:
        raise InvalidDocx("DOCX body is missing")
    for name in parts:
        for kind in ("header", "footer", "footnotes", "endnotes", "comments", "embeddings"):
            if name.startswith("word/" + kind):
                converter.warn("unsupported_part_" + kind)
                break
    rels = xml.get("word/_rels/document.xml.rels")
    if rels is not None:
        for rel in rels:
            if rel.get("TargetMode") == "External":
                converter.warn("external_relationship_ignored")
    try:
        content = LexicalContent.model_validate(
            {"root": element("root", converter.blocks(body) or [element("paragraph")])}
        )
    except ValidationError as exc:
        raise InvalidDocx(
            "Converted document exceeds supported structure or content limits"
        ) from exc
    converter.warn("formatting_normalized_to_template")
    return ImportResult(content, converter.warnings, list(converter.assets.values()))
