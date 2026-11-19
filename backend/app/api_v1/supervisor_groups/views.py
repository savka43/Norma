from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Response, status

from app.api_v1.auth.dependencies import SupervisorDep
from app.api_v1.dependencies import SessionDep
from app.api_v1.supervisor_groups import crud, service
from app.api_v1.supervisor_groups.dependencies import OwnedGroupDep
from app.api_v1.supervisor_groups.schemas import (
    GroupCreate,
    GroupPage,
    GroupResponse,
    MembershipResponse,
    PageParams,
    StudentAdd,
)
from app.api_v1.users.schemas import StudentPage, StudentSummary

router = APIRouter(prefix="/supervisor-groups", tags=["supervisor groups"])
PageParamsDep = Annotated[PageParams, Query()]


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_group(
    data: GroupCreate, supervisor: SupervisorDep, session: SessionDep
) -> GroupResponse:
    group = await service.create_group(session, supervisor.id, data)
    return GroupResponse.model_validate(group)


@router.get("")
async def list_groups(
    supervisor: SupervisorDep, session: SessionDep, params: PageParamsDep, response: Response
) -> GroupPage:
    groups = await crud.list_groups(session, supervisor.id, params)
    response.headers["Cache-Control"] = "no-store"
    return GroupPage(
        items=[GroupResponse.model_validate(group) for group in groups],
        limit=params.limit,
        offset=params.offset,
    )


@router.get("/{group_id}", responses={404: {"description": "Группа недоступна"}})
async def get_group(group: OwnedGroupDep, response: Response) -> GroupResponse:
    response.headers["Cache-Control"] = "no-store"
    return GroupResponse.model_validate(group)


@router.get("/{group_id}/students", responses={404: {"description": "Группа недоступна"}})
async def list_students(
    group: OwnedGroupDep, session: SessionDep, params: PageParamsDep, response: Response
) -> StudentPage:
    students = await crud.list_students(session, group.id, params)
    response.headers["Cache-Control"] = "no-store"
    return StudentPage(
        items=[StudentSummary.model_validate(student) for student in students],
        limit=params.limit,
        offset=params.offset,
    )


@router.post(
    "/{group_id}/students",
    status_code=status.HTTP_201_CREATED,
    responses={
        404: {"description": "Группа или студент недоступны"},
        409: {"description": "Студент уже состоит в группе"},
    },
)
async def add_student(
    data: StudentAdd, group: OwnedGroupDep, session: SessionDep
) -> MembershipResponse:
    try:
        membership = await service.add_student(session, group.id, data.student_id)
    except service.StudentNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Student not found") from exc
    except service.StudentAlreadyAssignedError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, "Student already belongs to a group") from exc
    return MembershipResponse.model_validate(membership)
