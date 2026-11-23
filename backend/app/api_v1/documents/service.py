from datetime import timedelta
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api_v1.documents import crud
from app.api_v1.documents.lexical import empty_content
from app.api_v1.documents.schemas import DocumentSave, RestoreRequest, VersionCreate
from app.api_v1.formatting import crud as formatting_crud
from app.core.models import (
    Document,
    DocumentEditLease,
    DocumentVersion,
    StageStatus,
    Thesis,
    ThesisStage,
)


async def require_template(session: AsyncSession, version_id: UUID, supervisor_id: UUID) -> None:
    if await formatting_crud.find_version(session, version_id, supervisor_id) is None:
        raise HTTPException(404, "Template version not found")


async def create_document(
    session: AsyncSession, thesis: Thesis, template_version_id: UUID
) -> Document:
    if await crud.find_by_thesis(session, thesis.id) is not None:
        raise HTTPException(409, "Thesis already has a document")
    await require_template(session, template_version_id, thesis.supervisor_id)
    document = Document(
        thesis_id=thesis.id, content=empty_content(), template_version_id=template_version_id
    )
    session.add(document)
    await session.commit()
    return document


async def acquire_lease(
    session: AsyncSession, document: Document, holder_id: UUID, seconds: int
) -> DocumentEditLease:
    now = await crud.database_now(session)
    lease = await crud.find_lease(session, document.id)
    if lease is not None and lease.expires_at > now:
        raise HTTPException(409, "Document already has an active edit lease")
    if lease is None:
        lease = DocumentEditLease(document_id=document.id)
        session.add(lease)
    lease.lease_id, lease.holder_id = uuid4(), holder_id
    lease.acquired_at, lease.expires_at = now, now + timedelta(seconds=seconds)
    await session.commit()
    return lease


async def require_lease(
    session: AsyncSession, document: Document, holder_id: UUID, lease_id: UUID
) -> DocumentEditLease:
    now = await crud.database_now(session)
    lease = await crud.find_lease(session, document.id)
    if (
        lease is None
        or lease.lease_id != lease_id
        or lease.holder_id != holder_id
        or lease.expires_at <= now
    ):
        raise HTTPException(409, "Edit lease is missing, expired or no longer owned")
    return lease


async def renew_lease(
    session: AsyncSession, document: Document, holder_id: UUID, lease_id: UUID, seconds: int
) -> DocumentEditLease:
    lease = await require_lease(session, document, holder_id, lease_id)
    lease.expires_at = await crud.database_now(session) + timedelta(seconds=seconds)
    await session.commit()
    return lease


async def release_lease(
    session: AsyncSession, document: Document, holder_id: UUID, lease_id: UUID
) -> None:
    lease = await crud.find_lease(session, document.id)
    if lease is not None:
        if lease.lease_id != lease_id or lease.holder_id != holder_id:
            raise HTTPException(409, "Edit lease is no longer owned")
        await session.delete(lease)
    await session.commit()


async def require_revision_and_lease(
    session: AsyncSession,
    document: Document,
    actor_id: UUID,
    lease_id: UUID,
    expected_revision: int,
) -> None:
    await require_lease(session, document, actor_id, lease_id)
    if document.revision != expected_revision:
        raise HTTPException(409, "Document revision conflict")


async def save_document(
    session: AsyncSession, document: Document, actor_id: UUID, lease_id: UUID, data: DocumentSave
) -> Document:
    await require_revision_and_lease(session, document, actor_id, lease_id, data.expected_revision)
    await require_editable(session, document)
    thesis = await session.get(Thesis, document.thesis_id)
    assert thesis is not None
    await require_template(session, data.template_version_id, thesis.supervisor_id)
    asset_ids = data.content.image_ids()
    if await crud.find_asset_ids(session, document.id, asset_ids) != asset_ids:
        raise HTTPException(422, "Image assets must belong to this document")
    document.content = data.content.stored()
    document.schema_version = data.schema_version
    document.template_version_id = data.template_version_id
    document.revision += 1
    document.updated_at = await crud.database_now(session)
    await session.commit()
    return document


async def add_snapshot(
    session: AsyncSession,
    document: Document,
    actor_id: UUID,
    comment: str | None,
    *,
    restored_from_id: UUID | None = None,
) -> DocumentVersion:
    document.last_version_number += 1
    version = DocumentVersion(
        document_id=document.id,
        number=document.last_version_number,
        document_revision=document.revision,
        content=document.content,
        schema_version=document.schema_version,
        template_version_id=document.template_version_id,
        created_by_id=actor_id,
        comment=comment,
        restored_from_id=restored_from_id,
    )
    session.add(version)
    await session.flush()
    return version


async def create_version(
    session: AsyncSession, document: Document, actor_id: UUID, lease_id: UUID, data: VersionCreate
) -> DocumentVersion:
    await require_revision_and_lease(session, document, actor_id, lease_id, data.expected_revision)
    version = await add_snapshot(session, document, actor_id, data.comment)
    await session.commit()
    return version


async def restore_version(
    session: AsyncSession, document: Document, actor_id: UUID, lease_id: UUID, data: RestoreRequest
) -> DocumentVersion:
    await require_revision_and_lease(session, document, actor_id, lease_id, data.expected_revision)
    await require_editable(session, document)
    source = await crud.find_version(session, data.version_id, document.id)
    if source is None:
        raise HTTPException(404, "Document version not found")
    document.content = source.content
    document.schema_version = source.schema_version
    document.template_version_id = source.template_version_id
    document.revision += 1
    document.updated_at = await crud.database_now(session)
    version = await add_snapshot(
        session, document, actor_id, data.comment, restored_from_id=source.id
    )
    await session.commit()
    return version


async def require_editable(session: AsyncSession, document: Document) -> None:
    # Caller holds the document lock; submit/decision also lock it before changing
    # any status. With whole-document submissions there are no editable subregions.
    reviewing = await session.scalar(
        select(ThesisStage.id)
        .where(
            ThesisStage.thesis_id == document.thesis_id,
            ThesisStage.status == StageStatus.IN_REVIEW,
        )
        .limit(1)
    )
    if reviewing is not None:
        raise HTTPException(409, "Document is locked while a stage is in review")
