from hashlib import sha256
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api_v1.documents import crud, service
from app.api_v1.documents.docx_import import ImportResult
from app.core.models import Document, DocumentAsset, DocumentImport, DocumentVersion, User


async def apply_import(
    session: AsyncSession,
    document_id: UUID,
    student: User,
    lease_id: UUID,
    expected_revision: int,
    source: bytes,
    result: ImportResult,
) -> tuple[Document, DocumentVersion, DocumentImport]:
    # Conversion takes place before this lock. Recheck lease/revision after waiting for it.
    document = await crud.find_document(session, document_id, student, lock=True)
    if document is None:
        raise HTTPException(404, "Document not found")
    await service.require_revision_and_lease(
        session, document, student.id, lease_id, expected_revision
    )
    previous = await service.add_snapshot(session, document, student.id, "Before DOCX import")
    document.content = result.content.stored()
    document.schema_version = 3 if result.content.requires_v3() else 2
    document.revision += 1
    document.updated_at = await crud.database_now(session)
    version = await service.add_snapshot(session, document, student.id, "DOCX import")
    record = DocumentImport(
        id=uuid4(),
        document_id=document.id,
        version_id=version.id,
        previous_version_id=previous.id,
        created_by_id=student.id,
        source=source,
        source_size=len(source),
        source_sha256=sha256(source).hexdigest(),
        warnings={code: count for code, count in result.warnings.items()},
    )
    session.add(record)
    await session.flush()
    session.add_all(
        [
            DocumentAsset(
                id=asset.id,
                document_id=document.id,
                import_id=record.id,
                data=asset.data,
                media_type=asset.media_type,
                width=asset.width,
                height=asset.height,
            )
            for asset in result.assets
        ]
    )
    await session.commit()
    return document, version, record
