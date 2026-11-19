from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api_v1.supervisor_groups import crud
from app.api_v1.supervisor_groups.schemas import GroupCreate
from app.core.models import GroupMembership, SupervisorGroup


class StudentNotFoundError(Exception):
    pass


class StudentAlreadyAssignedError(Exception):
    pass


async def create_group(
    session: AsyncSession, supervisor_id: UUID, data: GroupCreate
) -> SupervisorGroup:
    group = SupervisorGroup(
        supervisor_id=supervisor_id, name=data.name, academic_year=data.academic_year
    )
    session.add(group)
    await session.commit()
    return group


async def add_student(session: AsyncSession, group_id: UUID, student_id: UUID) -> GroupMembership:
    student = await crud.find_student(session, student_id)
    if student is None:
        raise StudentNotFoundError
    membership = GroupMembership(student_id=student.id, group_id=group_id)
    session.add(membership)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        cause = getattr(exc.orig, "__cause__", None)
        if getattr(cause, "constraint_name", None) == "pk_group_memberships":
            raise StudentAlreadyAssignedError from exc
        raise
    return membership
