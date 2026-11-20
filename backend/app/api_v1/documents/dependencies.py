from typing import Annotated
from uuid import UUID

from fastapi import Depends, Header, HTTPException

from app.api_v1.auth.dependencies import CurrentUserDep
from app.api_v1.dependencies import SessionDep
from app.api_v1.documents import crud
from app.api_v1.theses.crud import find_accessible_thesis
from app.core.models import Document, DocumentVersion, Thesis, User, UserRole


def get_student(user: CurrentUserDep) -> User:
    if user.role != UserRole.STUDENT:
        raise HTTPException(403, "Student role required")
    return user


StudentDep = Annotated[User, Depends(get_student)]
LeaseIdDep = Annotated[UUID, Header(alias="X-Edit-Lease")]


async def get_owned_thesis(thesis_id: UUID, user: StudentDep, session: SessionDep) -> Thesis:
    # A lock serializes explicit document creation for an existing thesis.
    thesis = await find_accessible_thesis(session, thesis_id, user, lock=True)
    if thesis is None:
        raise HTTPException(404, "Thesis not found")
    return thesis


async def get_accessible_document(
    document_id: UUID, user: CurrentUserDep, session: SessionDep
) -> Document:
    document = await crud.find_document(session, document_id, user)
    if document is None:
        raise HTTPException(404, "Document not found")
    return document


async def get_locked_owned_document(
    document_id: UUID, user: StudentDep, session: SessionDep
) -> Document:
    document = await crud.find_document(session, document_id, user, lock=True)
    if document is None:
        raise HTTPException(404, "Document not found")
    return document


async def get_accessible_version(
    version_id: UUID, user: CurrentUserDep, session: SessionDep
) -> DocumentVersion:
    version = await crud.find_version(session, version_id)
    if version is None or await crud.find_document(session, version.document_id, user) is None:
        raise HTTPException(404, "Document version not found")
    return version


OwnedThesisDep = Annotated[Thesis, Depends(get_owned_thesis)]
AccessibleDocumentDep = Annotated[Document, Depends(get_accessible_document)]
LockedOwnedDocumentDep = Annotated[Document, Depends(get_locked_owned_document)]
AccessibleVersionDep = Annotated[DocumentVersion, Depends(get_accessible_version)]
