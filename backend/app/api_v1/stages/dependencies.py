from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, status

from app.api_v1.auth.dependencies import CurrentUserDep, SupervisorDep
from app.api_v1.dependencies import SessionDep
from app.api_v1.stages.crud import find_accessible_stage
from app.api_v1.theses.crud import find_accessible_thesis
from app.core.models import Thesis, ThesisStage


async def get_accessible_stage(
    stage_id: UUID, user: CurrentUserDep, session: SessionDep
) -> ThesisStage:
    stage = await find_accessible_stage(session, stage_id, user)
    if stage is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Stage not found")
    return stage


async def get_stage_plan_for_update(
    stage_id: UUID, supervisor: SupervisorDep, session: SessionDep
) -> Thesis:
    stage = await find_accessible_stage(session, stage_id, supervisor)
    if stage is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Stage not found")
    thesis = await find_accessible_thesis(session, stage.thesis_id, supervisor, lock=True)
    if thesis is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Thesis not found")
    return thesis


AccessibleStageDep = Annotated[ThesisStage, Depends(get_accessible_stage)]
StagePlanForUpdateDep = Annotated[Thesis, Depends(get_stage_plan_for_update)]
