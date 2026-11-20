from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from app.api_v1.dependencies import SessionDep, SettingsDep
from app.api_v1.documents import crud, service
from app.api_v1.documents.dependencies import (
    AccessibleDocumentDep,
    AccessibleVersionDep,
    LeaseIdDep,
    LockedOwnedDocumentDep,
    OwnedThesisDep,
    StudentDep,
)
from app.api_v1.documents.schemas import (
    DocumentCreate,
    DocumentResponse,
    DocumentSave,
    LeaseResponse,
    RestoreRequest,
    RestoreResponse,
    VersionCreate,
    VersionPage,
    VersionResponse,
    VersionSummary,
)
from app.api_v1.supervisor_groups.schemas import PageParams
from app.api_v1.theses.dependencies import AccessibleThesisDep


def no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"


router = APIRouter(tags=["documents"], dependencies=[Depends(no_store)])
PageParamsDep = Annotated[PageParams, Query()]


@router.post(
    "/theses/{thesis_id}/document",
    status_code=201,
    responses={403: {}, 404: {}, 409: {}},
    response_model_exclude_unset=True,
)
async def create_document(
    data: DocumentCreate, thesis: OwnedThesisDep, session: SessionDep
) -> DocumentResponse:
    document = await service.create_document(session, thesis, data.template_version_id)
    return DocumentResponse.model_validate(document)


@router.get("/theses/{thesis_id}/document", responses={404: {}}, response_model_exclude_unset=True)
async def get_thesis_document(thesis: AccessibleThesisDep, session: SessionDep) -> DocumentResponse:
    document = await crud.find_by_thesis(session, thesis.id)
    if document is None:
        raise HTTPException(404, "Document not found")
    return DocumentResponse.model_validate(document)


@router.get("/documents/{document_id}", responses={404: {}}, response_model_exclude_unset=True)
async def get_document(document: AccessibleDocumentDep) -> DocumentResponse:
    return DocumentResponse.model_validate(document)


@router.put(
    "/documents/{document_id}",
    responses={403: {}, 404: {}, 409: {}},
    response_model_exclude_unset=True,
)
async def save_document(
    data: DocumentSave,
    document: LockedOwnedDocumentDep,
    student: StudentDep,
    lease_id: LeaseIdDep,
    session: SessionDep,
) -> DocumentResponse:
    saved = await service.save_document(session, document, student.id, lease_id, data)
    return DocumentResponse.model_validate(saved)


@router.post("/documents/{document_id}/edit-lease", status_code=201, responses={409: {}})
async def acquire_lease(
    document: LockedOwnedDocumentDep,
    student: StudentDep,
    session: SessionDep,
    settings: SettingsDep,
) -> LeaseResponse:
    lease = await service.acquire_lease(
        session, document, student.id, settings.document_lease_seconds
    )
    return LeaseResponse.model_validate(lease)


@router.post("/documents/{document_id}/edit-lease/renew", responses={409: {}})
async def renew_lease(
    document: LockedOwnedDocumentDep,
    student: StudentDep,
    lease_id: LeaseIdDep,
    session: SessionDep,
    settings: SettingsDep,
) -> LeaseResponse:
    lease = await service.renew_lease(
        session, document, student.id, lease_id, settings.document_lease_seconds
    )
    return LeaseResponse.model_validate(lease)


@router.delete("/documents/{document_id}/edit-lease", status_code=204, responses={409: {}})
async def release_lease(
    document: LockedOwnedDocumentDep, student: StudentDep, lease_id: LeaseIdDep, session: SessionDep
) -> None:
    await service.release_lease(session, document, student.id, lease_id)


@router.get("/documents/{document_id}/versions", responses={404: {}})
async def list_versions(
    document: AccessibleDocumentDep, session: SessionDep, params: PageParamsDep
) -> VersionPage:
    versions = await crud.list_versions(session, document.id, params)
    return VersionPage(
        items=[VersionSummary.model_validate(item) for item in versions],
        limit=params.limit,
        offset=params.offset,
    )


@router.post(
    "/documents/{document_id}/versions",
    status_code=201,
    responses={409: {}},
    response_model_exclude_unset=True,
)
async def create_version(
    data: VersionCreate,
    document: LockedOwnedDocumentDep,
    student: StudentDep,
    lease_id: LeaseIdDep,
    session: SessionDep,
) -> VersionResponse:
    version = await service.create_version(session, document, student.id, lease_id, data)
    return VersionResponse.model_validate(version)


@router.get(
    "/document-versions/{version_id}", responses={404: {}}, response_model_exclude_unset=True
)
async def get_version(version: AccessibleVersionDep) -> VersionResponse:
    return VersionResponse.model_validate(version)


@router.post(
    "/documents/{document_id}/restore", responses={409: {}}, response_model_exclude_unset=True
)
async def restore_version(
    data: RestoreRequest,
    document: LockedOwnedDocumentDep,
    student: StudentDep,
    lease_id: LeaseIdDep,
    session: SessionDep,
) -> RestoreResponse:
    version = await service.restore_version(session, document, student.id, lease_id, data)
    return RestoreResponse(
        document=DocumentResponse.model_validate(document),
        version=VersionResponse.model_validate(version),
    )
