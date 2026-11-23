from collections.abc import Collection
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from starlette.concurrency import run_in_threadpool

from app.api_v1.dependencies import SessionDep
from app.api_v1.documents import crud, service
from app.api_v1.documents.dependencies import AccessibleDocumentDep, LeaseIdDep, StudentDep
from app.api_v1.documents.docx_import import (
    DOCX_MEDIA_TYPE,
    MAX_UPLOAD_BYTES,
    InvalidDocx,
    convert_docx,
)
from app.api_v1.documents.images import (
    IMAGE_FORMATS,
    ImageLimitExceeded,
    InvalidImage,
    normalize_image,
)
from app.api_v1.documents.import_schemas import (
    AssetResponse,
    AssetUploadParams,
    ImportPage,
    ImportParams,
    ImportResponse,
    ImportSummary,
)
from app.api_v1.documents.import_service import apply_import
from app.api_v1.documents.schemas import DocumentResponse, VersionResponse
from app.api_v1.documents.views import PageParamsDep, no_store

router = APIRouter(tags=["documents"], dependencies=[Depends(no_store)])


async def read_upload_body(request: Request, media_types: Collection[str]) -> tuple[bytes, str]:
    media_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if media_type not in media_types:
        raise HTTPException(415, "Use a supported Content-Type and send the raw file as the body")
    if request.headers.get("content-encoding", "identity").lower() != "identity":
        raise HTTPException(415, "Encoded request bodies are not supported")
    length = request.headers.get("content-length")
    if length is not None:
        try:
            size = int(length)
        except ValueError as exc:
            raise HTTPException(400, "Invalid Content-Length") from exc
        if size < 0:
            raise HTTPException(400, "Invalid Content-Length")
        if size > MAX_UPLOAD_BYTES:
            raise HTTPException(413, "Upload limit is 10 MiB")
    data = bytearray()
    async for chunk in request.stream():
        if len(data) + len(chunk) > MAX_UPLOAD_BYTES:
            raise HTTPException(413, "Upload limit is 10 MiB")
        data.extend(chunk)
    return bytes(data), media_type


@router.post(
    "/documents/{document_id}/import",
    status_code=201,
    responses={400: {}, 403: {}, 404: {}, 409: {}, 413: {}, 415: {}},
    response_model_exclude_unset=True,
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {DOCX_MEDIA_TYPE: {"schema": {"type": "string", "format": "binary"}}},
        }
    },
)
async def import_document(
    request: Request,
    params: Annotated[ImportParams, Query()],
    document: AccessibleDocumentDep,
    student: StudentDep,
    lease_id: LeaseIdDep,
    session: SessionDep,
) -> ImportResponse:
    await service.require_revision_and_lease(
        session, document, student.id, lease_id, params.expected_revision
    )
    source, _ = await read_upload_body(request, (DOCX_MEDIA_TYPE,))
    try:
        result = await run_in_threadpool(convert_docx, source)
    except InvalidDocx as exc:
        raise HTTPException(422, str(exc)) from exc
    saved, version, record = await apply_import(
        session, document.id, student, lease_id, params.expected_revision, source, result
    )
    return ImportResponse(
        document=DocumentResponse.model_validate(saved),
        version=VersionResponse.model_validate(version),
        import_record=ImportSummary.model_validate(record),
    )


@router.get("/documents/{document_id}/imports", responses={404: {}})
async def list_imports(
    document: AccessibleDocumentDep, session: SessionDep, params: PageParamsDep
) -> ImportPage:
    records = await crud.list_imports(session, document.id, params)
    return ImportPage(
        items=[ImportSummary.model_validate(record) for record in records],
        limit=params.limit,
        offset=params.offset,
    )


@router.get(
    "/documents/{document_id}/imports/{import_id}/source",
    response_class=Response,
    responses={
        200: {"content": {DOCX_MEDIA_TYPE: {"schema": {"type": "string", "format": "binary"}}}},
        404: {},
    },
)
async def download_source(
    import_id: UUID, document: AccessibleDocumentDep, session: SessionDep
) -> Response:
    source = await crud.find_import_source(session, document.id, import_id)
    if source is None:
        raise HTTPException(404, "Import not found")
    return Response(
        source,
        media_type=DOCX_MEDIA_TYPE,
        headers={
            "Content-Disposition": f'attachment; filename="{import_id}.docx"',
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get(
    "/documents/{document_id}/assets/{asset_id}",
    response_class=Response,
    responses={
        200: {"content": {"image/png": {"schema": {"type": "string", "format": "binary"}}}},
        404: {},
    },
)
async def get_asset(
    asset_id: UUID, document: AccessibleDocumentDep, session: SessionDep
) -> Response:
    asset = await crud.find_asset(session, document.id, asset_id)
    if asset is None:
        raise HTTPException(404, "Image asset not found")
    return Response(
        asset.data,
        media_type=asset.media_type,
        headers={
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "default-src 'none'; sandbox",
        },
    )


@router.post(
    "/documents/{document_id}/assets",
    status_code=201,
    responses={400: {}, 403: {}, 404: {}, 409: {}, 413: {}, 415: {}},
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                media_type: {"schema": {"type": "string", "format": "binary"}}
                for media_type in IMAGE_FORMATS
            },
        }
    },
)
async def upload_asset(
    request: Request,
    params: Annotated[AssetUploadParams, Query()],
    document: AccessibleDocumentDep,
    student: StudentDep,
    lease_id: LeaseIdDep,
    session: SessionDep,
) -> AssetResponse:
    await service.require_revision_and_lease(
        session, document, student.id, lease_id, params.expected_revision
    )
    source, media_type = await read_upload_body(request, IMAGE_FORMATS)
    try:
        image = await run_in_threadpool(normalize_image, source, media_type=media_type)
    except ImageLimitExceeded as exc:
        raise HTTPException(413, str(exc)) from exc
    except InvalidImage as exc:
        raise HTTPException(422, str(exc)) from exc
    if len(image.data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "Normalized image exceeds 10 MiB")
    asset = await service.create_image_asset(
        session, document.id, student, lease_id, params.expected_revision, image
    )
    return AssetResponse.model_validate(asset)
