from uuid import UUID

from fastapi import APIRouter, HTTPException, Response
from starlette.concurrency import run_in_threadpool

from app.api_v1.dependencies import SessionDep
from app.api_v1.documents import crud
from app.api_v1.documents.dependencies import AccessibleDocumentDep
from app.api_v1.documents.diff import DiffResponse, compare_versions

router = APIRouter(tags=["documents"])


@router.get("/documents/{document_id}/diff", responses={404: {}, 422: {}})
async def get_version_diff(
    document: AccessibleDocumentDep,
    base: UUID,
    target: UUID,
    session: SessionDep,
    response: Response,
) -> DiffResponse:
    first = await crud.find_version(session, base, document.id)
    second = await crud.find_version(session, target, document.id)
    if first is None or second is None:
        raise HTTPException(404, "Document version not found")
    response.headers["Cache-Control"] = "no-store"
    return await run_in_threadpool(compare_versions, first, second)
