from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api_v1.theses import crud
from app.api_v1.theses.schemas import ThesisCreate
from app.core.models import Thesis


class StudentNotFoundError(Exception):
    pass


class ThesisAlreadyExistsError(Exception):
    pass


async def create_thesis(session: AsyncSession, supervisor_id: UUID, data: ThesisCreate) -> Thesis:
    if await crud.find_assigned_student(session, data.student_id, supervisor_id) is None:
        raise StudentNotFoundError
    thesis = Thesis(supervisor_id=supervisor_id, **data.model_dump())
    session.add(thesis)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        cause = getattr(exc.orig, "__cause__", None)
        if getattr(cause, "constraint_name", None) == "uq_theses_student_id":
            raise ThesisAlreadyExistsError from exc
        raise
    return thesis
