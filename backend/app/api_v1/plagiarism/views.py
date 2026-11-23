from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api_v1.auth.dependencies import CurrentUserDep
from app.api_v1.dependencies import SessionDep, SettingsDep
from app.api_v1.documents import crud as documents
from app.api_v1.documents.dependencies import AccessibleVersionDep, StudentDep
from app.api_v1.documents.views import no_store
from app.api_v1.plagiarism import crud, service
from app.api_v1.plagiarism.schemas import CheckCreate, CheckPage, CheckReport, CheckResponse
from app.api_v1.supervisor_groups.schemas import PageParams
from app.core.models import CheckStatus, PlagiarismCheck

router = APIRouter(tags=["plagiarism"], dependencies=[Depends(no_store)])
version_checks = "/document-versions/{version_id}/plagiarism-checks"


async def get_accessible_check(
    check_id: UUID, session: SessionDep, user: CurrentUserDep
) -> PlagiarismCheck:
    check = await session.get(PlagiarismCheck, check_id)
    if check is not None:
        version = await documents.find_version(session, check.version_id)
        if version is not None and await documents.find_document(
            session, version.document_id, user
        ):
            return check
    raise HTTPException(404, "Plagiarism check not found")


AccessibleCheckDep = Annotated[PlagiarismCheck, Depends(get_accessible_check)]


@router.post(version_checks, status_code=202, responses={403: {}, 404: {}, 409: {}, 503: {}})
async def create_check(
    _data: CheckCreate,
    student: StudentDep,
    version: AccessibleVersionDep,
    session: SessionDep,
    settings: SettingsDep,
) -> CheckResponse:
    return CheckResponse.model_validate(await service.enqueue(session, version, student, settings))


@router.get(version_checks, responses={404: {}})
async def list_checks(
    version: AccessibleVersionDep, session: SessionDep, params: Annotated[PageParams, Query()]
) -> CheckPage:
    checks = await crud.list_checks(session, version.id, params.limit, params.offset)
    return CheckPage(
        items=[CheckResponse.model_validate(check) for check in checks],
        limit=params.limit,
        offset=params.offset,
    )


@router.get("/plagiarism-checks/{check_id}", responses={404: {}})
async def get_check(check: AccessibleCheckDep) -> CheckResponse:
    return CheckResponse.model_validate(check)


@router.get("/plagiarism-checks/{check_id}/report", responses={404: {}, 409: {}})
async def get_report(check: AccessibleCheckDep) -> CheckReport:
    if check.status != CheckStatus.COMPLETED:
        raise HTTPException(409, "Plagiarism report is not available")
    return CheckReport.model_validate(check.result)
