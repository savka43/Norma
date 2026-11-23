from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api_v1.comments import crud
from app.api_v1.comments.schemas import (
    CommentAnchor,
    CommentCreate,
    CommentListParams,
    CommentResponse,
)
from app.api_v1.documents.structure import SemanticBlock, semantic_blocks, utf16_length, utf16_slice
from app.api_v1.supervisor_groups.schemas import PageParams
from app.core.models import Comment, CommentEvent, Document, DocumentVersion


def validate_anchor(blocks: list[SemanticBlock], anchor: CommentAnchor, quote: str) -> None:
    block = next((item for item in blocks if item.block_id == anchor.block_id), None)
    if block is None or utf16_slice(block.text, anchor.offset_start, anchor.offset_end) != quote:
        raise HTTPException(422, "Quote and anchor must match the source version")


def locate_anchor(
    blocks: list[SemanticBlock],
    anchor: CommentAnchor,
    quote: str,
    source: list[SemanticBlock],
) -> CommentAnchor | None:
    original = next((block for block in source if block.block_id == anchor.block_id), None)
    current = next((block for block in blocks if block.block_id == anchor.block_id), None)
    if original is not None and current is not None and current.node == original.node:
        return anchor
    # An exact position is not enough when repeated text makes the origin ambiguous.
    # Relocate only a unique exact quote; never silently attach to another duplicate.
    matches: list[CommentAnchor] = []
    for block in blocks:
        start = block.text.find(quote)
        while start >= 0:
            matches.append(
                CommentAnchor(
                    block_id=block.block_id,
                    offset_start=utf16_length(block.text[:start]),
                    offset_end=utf16_length(block.text[: start + len(quote)]),
                )
            )
            if len(matches) > 1:
                return None
            start = block.text.find(quote, start + 1)
    return matches[0] if matches else None


def comment_response(
    comment: Comment, blocks: list[SemanticBlock], source: list[SemanticBlock]
) -> CommentResponse:
    result = CommentResponse.model_validate(comment)
    result.current_anchor = locate_anchor(blocks, result.anchor, result.quote, source)
    result.is_detached = result.current_anchor is None
    return result


async def current_blocks(session: AsyncSession, document_id: UUID) -> list[SemanticBlock]:
    document = await session.get(Document, document_id, populate_existing=True)
    assert document is not None
    return semantic_blocks(document.content)


async def visible_comments(
    session: AsyncSession, version: DocumentVersion, params: CommentListParams
) -> list[CommentResponse]:
    blocks = await current_blocks(session, version.document_id)
    source = semantic_blocks(version.content)
    if params.include_detached:
        comments = await crud.list_comments(session, version.id, params, params.include_resolved)
        return [comment_response(item, blocks, source) for item in comments]
    # Filter the projection before pagination: detached rows must not leave gaps
    # or consume the requested visible-page offset. Fetch source rows in batches.
    result: list[CommentResponse] = []
    scanned, visible = 0, 0
    while len(result) < params.limit:
        comments = await crud.list_comments(
            session, version.id, PageParams(limit=100, offset=scanned), params.include_resolved
        )
        for item in comments:
            projected = comment_response(item, blocks, source)
            if not projected.is_detached:
                if visible >= params.offset:
                    result.append(projected)
                    if len(result) == params.limit:
                        return result
                visible += 1
        if len(comments) < 100:
            break
        scanned += len(comments)
    return result


async def create_comment(
    session: AsyncSession, version: DocumentVersion, author_id: UUID, data: CommentCreate
) -> Comment:
    validate_anchor(semantic_blocks(version.content), data.anchor, data.quote)
    comment = Comment(
        version_id=version.id,
        author_id=author_id,
        body=data.body,
        quote=data.quote,
        anchor=data.anchor.model_dump(mode="json"),
    )
    session.add(comment)
    await session.flush()
    session.add(CommentEvent(comment_id=comment.id, actor_id=author_id, revision=1, status="open"))
    await session.commit()
    return comment


async def resolve_comment(
    session: AsyncSession, comment: Comment, actor_id: UUID, expected_revision: int
) -> None:
    if comment.revision != expected_revision or comment.status != "open":
        raise HTTPException(409, "Comment status or revision conflict")
    comment.status, comment.revision = "resolved", comment.revision + 1
    session.add(
        CommentEvent(
            comment_id=comment.id,
            actor_id=actor_id,
            revision=comment.revision,
            status="resolved",
        )
    )
    await session.commit()
