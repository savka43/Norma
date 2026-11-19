from typing import Annotated

from fastapi import APIRouter, Query, Response

from app.api_v1.auth.dependencies import SupervisorDep
from app.api_v1.dependencies import SessionDep
from app.api_v1.users import crud
from app.api_v1.users.schemas import StudentPage, StudentSearchParams, StudentSummary

router = APIRouter(prefix="/students", tags=["students"])


@router.get("", summary="Поиск свободных зарегистрированных студентов")
async def search_students(
    params: Annotated[StudentSearchParams, Query()],
    session: SessionDep,
    _supervisor: SupervisorDep,
    response: Response,
) -> StudentPage:
    students = await crud.search_available_students(session, params)
    response.headers["Cache-Control"] = "no-store"
    return StudentPage(
        items=[StudentSummary.model_validate(student) for student in students],
        limit=params.limit,
        offset=params.offset,
    )
