from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api_v1.supervisor_groups.schemas import PageParams
from app.core.models import Document, DocumentEditLease, DocumentVersion, Thesis, User, UserRole


async def find_document(
    session: AsyncSession, document_id: UUID, user: User, *, lock: bool = False
) -> Document | None:
    statement = (
        select(Document)
        .join(Thesis, Thesis.id == Document.thesis_id)
        .where(
            Document.id == document_id,
            Thesis.student_id == user.id
            if user.role == UserRole.STUDENT
            else Thesis.supervisor_id == user.id,
        )
    )
    if lock:
        statement = statement.with_for_update(of=Document).execution_options(populate_existing=True)
    return await session.scalar(statement)


async def find_by_thesis(session: AsyncSession, thesis_id: UUID) -> Document | None:
    return await session.scalar(select(Document).where(Document.thesis_id == thesis_id))


async def database_now(session: AsyncSession) -> datetime:
    # Read wall-clock time after waiting for the document lock, not transaction-start now().
    return cast(datetime, await session.scalar(select(func.clock_timestamp())))


async def find_lease(session: AsyncSession, document_id: UUID) -> DocumentEditLease | None:
    return await session.scalar(
        select(DocumentEditLease)
        .where(DocumentEditLease.document_id == document_id)
        .execution_options(populate_existing=True)
    )


async def find_version(
    session: AsyncSession, version_id: UUID, document_id: UUID | None = None
) -> DocumentVersion | None:
    statement = select(DocumentVersion).where(DocumentVersion.id == version_id)
    if document_id is not None:
        statement = statement.where(DocumentVersion.document_id == document_id)
    return await session.scalar(statement)


async def list_versions(
    session: AsyncSession, document_id: UUID, params: PageParams
) -> list[DocumentVersion]:
    return list(
        await session.scalars(
            select(DocumentVersion)
            .where(DocumentVersion.document_id == document_id)
            .order_by(DocumentVersion.number.desc())
            .limit(params.limit)
            .offset(params.offset)
        )
    )
