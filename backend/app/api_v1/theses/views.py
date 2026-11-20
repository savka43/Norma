from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Response, status

from app.api_v1.auth.dependencies import CurrentUserDep, SupervisorDep
from app.api_v1.dependencies import SessionDep
from app.api_v1.stages import crud as stages_crud
from app.api_v1.stages.service import thesis_response
from app.api_v1.supervisor_groups.schemas import PageParams
from app.api_v1.theses import crud, service
from app.api_v1.theses.dependencies import AccessibleThesisDep
from app.api_v1.theses.schemas import ThesisCreate, ThesisPage, ThesisResponse
from app.core.models import ThesisStage

router = APIRouter(prefix="/theses", tags=["theses"])
PageParamsDep = Annotated[PageParams, Query()]


@router.post("", status_code=status.HTTP_201_CREATED, responses={404: {}, 409: {}})
async def create_thesis(
    data: ThesisCreate, supervisor: SupervisorDep, session: SessionDep
) -> ThesisResponse:
    try:
        thesis = await service.create_thesis(session, supervisor.id, data)
    except service.StudentNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Student not found") from exc
    except service.ThesisAlreadyExistsError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, "Student already has a thesis") from exc
    return thesis_response(thesis, [], datetime.now(UTC).date())


@router.get("")
async def list_theses(
    user: CurrentUserDep, session: SessionDep, params: PageParamsDep, response: Response
) -> ThesisPage:
    theses = await crud.list_theses(session, user, params)
    stages = await stages_crud.list_stages(session, [thesis.id for thesis in theses])
    stages_by_thesis: dict[UUID, list[ThesisStage]] = {}
    for stage in stages:
        stages_by_thesis.setdefault(stage.thesis_id, []).append(stage)
    as_of = datetime.now(UTC).date()
    response.headers["Cache-Control"] = "no-store"
    return ThesisPage(
        items=[
            thesis_response(thesis, stages_by_thesis.get(thesis.id, []), as_of) for thesis in theses
        ],
        limit=params.limit,
        offset=params.offset,
    )


@router.get("/{thesis_id}", responses={404: {}})
async def get_thesis(
    thesis: AccessibleThesisDep, session: SessionDep, response: Response
) -> ThesisResponse:
    stages = await stages_crud.list_stages(session, [thesis.id])
    response.headers["Cache-Control"] = "no-store"
    return thesis_response(thesis, stages, datetime.now(UTC).date())
