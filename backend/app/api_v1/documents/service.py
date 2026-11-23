from datetime import timedelta
from uuid import UUID, uuid4

from fastapi import HTTPException
from pydantic import JsonValue
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api_v1.documents import crud
from app.api_v1.documents.chapters import preserves_chapters
from app.api_v1.documents.images import NormalizedImage
from app.api_v1.documents.lexical import empty_content
from app.api_v1.documents.schemas import DocumentSave, RestoreRequest, VersionCreate
from app.api_v1.formatting import crud as formatting_crud
from app.core.models import (
    Document,
    DocumentAsset,
    DocumentEditLease,
    DocumentVersion,
    StageStatus,
    StageSubmission,
    Thesis,
    ThesisStage,
    User,
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
    content = data.content.stored()
    await require_editable(session, document, content, data.template_version_id)
    stage_ids = data.content.chapter_stage_ids()
    if stage_ids:
        matching = await session.scalars(
            select(ThesisStage.id).where(ThesisStage.thesis_id == document.thesis_id)
        )
        if not stage_ids.issubset(matching):
            raise HTTPException(422, "Chapter stages must belong to this thesis")
    thesis = await session.get(Thesis, document.thesis_id)
    assert thesis is not None
    await require_template(session, data.template_version_id, thesis.supervisor_id)
    asset_ids = data.content.image_ids()
    if await crud.find_asset_ids(session, document.id, asset_ids) != asset_ids:
        raise HTTPException(422, "Image assets must belong to this document")
    document.content = content
    document.schema_version = data.schema_version
    document.template_version_id = data.template_version_id
    document.revision += 1
    document.updated_at = await crud.database_now(session)
    await session.commit()
    return document


async def create_image_asset(
    session: AsyncSession,
    document_id: UUID,
    student: User,
    lease_id: UUID,
    expected_revision: int,
    image: NormalizedImage,
) -> DocumentAsset:
    document = await crud.find_document(session, document_id, student, lock=True)
    if document is None:
        raise HTTPException(404, "Document not found")
    await require_revision_and_lease(session, document, student.id, lease_id, expected_revision)
    asset = DocumentAsset(
        document_id=document.id,
        media_type="image/png",
        data=image.data,
        width=image.width,
        height=image.height,
    )
    session.add(asset)
    await session.commit()
    return asset


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
    source = await crud.find_version(session, data.version_id, document.id)
    if source is None:
        raise HTTPException(404, "Document version not found")
    await require_editable(session, document, source.content, source.template_version_id)
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


async def require_editable(
    session: AsyncSession,
    document: Document,
    content: dict[str, JsonValue] | None = None,
    template_version_id: UUID | None = None,
) -> None:
    # Every writer and review transition holds the document lock. Comparing with
    # the working draft therefore preserves the protected blocks from submission onward.
    reviewing = (
        await session.execute(
            select(ThesisStage.id, StageSubmission.scope)
            .outerjoin(
                StageSubmission,
                (StageSubmission.stage_id == ThesisStage.id)
                & (StageSubmission.version_id == ThesisStage.submitted_version_id),
            )
            .where(
                ThesisStage.thesis_id == document.thesis_id,
                ThesisStage.status == StageStatus.IN_REVIEW,
            )
        )
    ).all()
    if not reviewing:
        return
    if content is None or any(scope != "chapter" for _, scope in reviewing):
        raise HTTPException(409, "Document is locked while a stage is in review")
    if template_version_id != document.template_version_id:
        raise HTTPException(409, "Document template is locked while a chapter is in review")
    if not preserves_chapters(document.content, content, {stage_id for stage_id, _ in reviewing}):
        raise HTTPException(409, "Document changes affect a chapter in review")
