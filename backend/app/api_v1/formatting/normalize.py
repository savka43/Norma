from copy import deepcopy
from typing import cast

from pydantic import JsonValue

from app.api_v1.documents.lexical import content_nodes
from app.api_v1.formatting.document_schemas import FormattingIssue
from app.api_v1.formatting.schemas import TemplateParameters, TextStyle

# Preserve semantic emphasis, underline, strikeout and sub/superscript.
# Code/highlight/case transformations are manual presentation overrides.
SEMANTIC_TEXT_MASK = 1 | 2 | 4 | 8 | 32 | 64
MAX_REPORTED_ISSUES = 1000


def block_style(
    node: dict[str, JsonValue], parameters: TemplateParameters, *, in_table: bool = False
) -> TextStyle:
    if node["type"] == "heading":
        return parameters.headings[int(str(node["tag"])[1:]) - 1]
    if node["type"] == "norma-caption":
        return parameters.caption
    if node["type"] in ("list", "listitem"):
        return parameters.list
    return (
        parameters.table
        if in_table or node["type"] in ("table", "tablerow", "tablecell")
        else parameters.body
    )


def formatting_issues(
    content: dict[str, JsonValue], parameters: TemplateParameters
) -> list[FormattingIssue]:
    issues: list[FormattingIssue] = []

    def visit(node: dict[str, JsonValue], path: str, in_table: bool = False) -> None:
        kind = node["type"]
        if kind == "text":
            flags = cast(int, node["format"])
            expected = flags & SEMANTIC_TEXT_MASK
            if flags != expected:
                issues.append(
                    FormattingIssue(
                        path=path + ".format",
                        code="text_effect_override",
                        actual=flags,
                        expected=expected,
                    )
                )
        elif "children" in node:
            alignment = node["format"]
            expected = block_style(node, parameters, in_table=in_table).alignment
            if alignment and alignment != expected:
                issues.append(
                    FormattingIssue(
                        path=path + ".format",
                        code="alignment_override",
                        actual=alignment,
                        expected=expected,
                    )
                )
            if node["indent"] != 0:
                issues.append(
                    FormattingIssue(
                        path=path + ".indent",
                        code="indent_override",
                        actual=node["indent"],
                        expected=0,
                    )
                )
        for index, child in enumerate(cast(list[JsonValue], node.get("children", []))):
            visit(
                cast(dict[str, JsonValue], child),
                f"{path}.children[{index}]",
                in_table or kind == "table",
            )

    visit(cast(dict[str, JsonValue], content["root"]), "root")
    return issues


def normalize(content: dict[str, JsonValue]) -> dict[str, JsonValue]:
    result = deepcopy(content)
    for node in content_nodes(result):
        if node["type"] == "text":
            node["format"] = cast(int, node["format"]) & SEMANTIC_TEXT_MASK
        elif "children" in node:
            node["format"] = ""
            node["indent"] = 0
    return result
