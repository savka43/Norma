from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Response, status

from app.api_v1.auth.dependencies import SupervisorDep
from app.api_v1.dependencies import SessionDep
from app.api_v1.stages import crud, service
from app.api_v1.stages.dependencies import AccessibleStageDep, StagePlanForUpdateDep
from app.api_v1.stages.schemas import (
    GroupProgressPage,
    StageEventResponse,
    StageHistoryPage,
    StagePage,
    StageWrite,
    StudentProgress,
)
from app.api_v1.supervisor_groups.dependencies import OwnedGroupDep
from app.api_v1.supervisor_groups.schemas import PageParams
from app.api_v1.theses.dependencies import AccessibleThesisDep, LockedOwnedThesisDep
from app.api_v1.users.schemas import StudentSummary
from app.core.models import ThesisStage

router = APIRouter(tags=["stages"])
PageParamsDep = Annotated[PageParams, Query()]


@router.get("/theses/{thesis_id}/stages", responses={404: {}})
async def list_stages(
    thesis: AccessibleThesisDep, session: SessionDep, response: Response
) -> StagePage:
    stages = await crud.list_stages(session, [thesis.id])
    as_of = datetime.now(UTC).date()
    response.headers["Cache-Control"] = "no-store"
    return StagePage(
        items=[service.stage_response(stage, as_of) for stage in stages],
        revision=thesis.revision,
        as_of_date=as_of,
    )


@router.post(
    "/theses/{thesis_id}/stages",
    status_code=status.HTTP_201_CREATED,
    responses={403: {}, 404: {}, 409: {}},
)
async def create_stage(
    data: StageWrite, thesis: LockedOwnedThesisDep, supervisor: SupervisorDep, session: SessionDep
) -> StagePage:
    stages = await service.write_stage(session, thesis, supervisor.id, data)
    as_of = datetime.now(UTC).date()
    return StagePage(
        items=[service.stage_response(stage, as_of) for stage in stages],
        revision=thesis.revision,
        as_of_date=as_of,
    )


@router.patch("/stages/{stage_id}", responses={403: {}, 404: {}, 409: {}})
async def update_stage(
    stage_id: UUID,
    data: StageWrite,
    thesis: StagePlanForUpdateDep,
    supervisor: SupervisorDep,
    session: SessionDep,
) -> StagePage:
    stages = await service.write_stage(session, thesis, supervisor.id, data, stage_id=stage_id)
    as_of = datetime.now(UTC).date()
    return StagePage(
        items=[service.stage_response(stage, as_of) for stage in stages],
        revision=thesis.revision,
        as_of_date=as_of,
    )


@router.get("/stages/{stage_id}/history", responses={404: {}})
async def get_history(
    stage: AccessibleStageDep, session: SessionDep, params: PageParamsDep, response: Response
) -> StageHistoryPage:
    events = await crud.list_history(session, stage.id, params)
    response.headers["Cache-Control"] = "no-store"
    return StageHistoryPage(
        items=[StageEventResponse.model_validate(event) for event in events],
        limit=params.limit,
        offset=params.offset,
    )


@router.get("/supervisor-groups/{group_id}/progress", responses={403: {}, 404: {}})
async def get_group_progress(
    group: OwnedGroupDep, session: SessionDep, params: PageParamsDep, response: Response
) -> GroupProgressPage:
    rows = await crud.list_group_theses(session, group.id, params)
    stages = await crud.list_stages(
        session, [thesis.id for _, thesis in rows if thesis is not None]
    )
    by_thesis: dict[UUID, list[ThesisStage]] = {}
    for stage in stages:
        by_thesis.setdefault(stage.thesis_id, []).append(stage)
    as_of = datetime.now(UTC).date()
    response.headers["Cache-Control"] = "no-store"
    return GroupProgressPage(
        items=[
            StudentProgress(
                student=StudentSummary.model_validate(student),
                thesis=service.thesis_response(thesis, by_thesis.get(thesis.id, []), as_of)
                if thesis
                else None,
                stages=[
                    service.stage_response(stage, as_of) for stage in by_thesis.get(thesis.id, [])
                ]
                if thesis
                else [],
            )
            for student, thesis in rows
        ],
        limit=params.limit,
        offset=params.offset,
        as_of_date=as_of,
    )
