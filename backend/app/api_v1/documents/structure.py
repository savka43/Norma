"""Version-local semantic block paths; offsets use Lexical/JavaScript UTF-16 units."""

from dataclasses import dataclass

from pydantic import JsonValue


@dataclass(frozen=True)
class SemanticBlock:
    block_id: str
    kind: str
    text: str
    node: dict[str, JsonValue]


def inline_text(node: dict[str, JsonValue]) -> str:
    if node.get("type") == "text":
        return str(node.get("text", ""))
    if node.get("type") == "linebreak":
        return "\n"
    if node.get("type") == "norma-image":
        return "\ufffc"
    children = node.get("children", [])
    if not isinstance(children, list):
        return ""
    return "".join(
        inline_text(child)
        for child in children
        if isinstance(child, dict) and child.get("type") != "list"
    )


def semantic_blocks(content: dict[str, JsonValue]) -> list[SemanticBlock]:
    blocks: list[SemanticBlock] = []

    def visit(node: JsonValue, path: str) -> None:
        if not isinstance(node, dict):
            return
        kind = str(node.get("type", ""))
        if kind in {"paragraph", "heading", "quote", "norma-caption", "listitem"}:
            blocks.append(SemanticBlock(path, kind, inline_text(node), node))
        children = node.get("children", [])
        if isinstance(children, list):
            for index, child in enumerate(children):
                visit(child, f"{path}/{index}" if path else str(index))

    visit(content["root"], "")
    return blocks


def utf16_length(text: str) -> int:
    return len(text.encode("utf-16-le")) // 2


def utf16_slice(text: str, start: int, end: int) -> str | None:
    data = text.encode("utf-16-le")
    if not 0 <= start < end <= len(data) // 2:
        return None
    try:
        return data[start * 2 : end * 2].decode("utf-16-le")
    except UnicodeDecodeError:
        return None
