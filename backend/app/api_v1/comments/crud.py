from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api_v1.supervisor_groups.schemas import PageParams
from app.core.models import Comment, CommentEvent


async def find_comment(
    session: AsyncSession, comment_id: UUID, *, lock: bool = False
) -> Comment | None:
    query = select(Comment).where(Comment.id == comment_id)
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    return await session.scalar(query)


async def list_comments(
    session: AsyncSession, version_id: UUID, params: PageParams, include_resolved: bool
) -> list[Comment]:
    query = select(Comment).where(Comment.version_id == version_id)
    if not include_resolved:
        query = query.where(Comment.status == "open")
    return list(
        await session.scalars(
            query.order_by(Comment.created_at, Comment.id).limit(params.limit).offset(params.offset)
        )
    )


async def list_history(
    session: AsyncSession, comment_id: UUID, params: PageParams
) -> list[CommentEvent]:
    return list(
        await session.scalars(
            select(CommentEvent)
            .where(CommentEvent.comment_id == comment_id)
            .order_by(CommentEvent.revision)
            .limit(params.limit)
            .offset(params.offset)
        )
    )
