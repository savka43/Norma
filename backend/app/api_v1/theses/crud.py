from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api_v1.supervisor_groups.schemas import PageParams
from app.core.models import GroupMembership, SupervisorGroup, Thesis, User, UserRole


async def find_assigned_student(
    session: AsyncSession, student_id: UUID, supervisor_id: UUID
) -> UUID | None:
    return await session.scalar(
        select(User.id)
        .join(GroupMembership, GroupMembership.student_id == User.id)
        .join(SupervisorGroup, SupervisorGroup.id == GroupMembership.group_id)
        .where(
            User.id == student_id,
            User.role == UserRole.STUDENT,
            SupervisorGroup.supervisor_id == supervisor_id,
        )
    )


async def find_accessible_thesis(
    session: AsyncSession, thesis_id: UUID, user: User, *, lock: bool = False
) -> Thesis | None:
    statement = select(Thesis).where(
        Thesis.id == thesis_id,
        Thesis.supervisor_id == user.id
        if user.role == UserRole.SUPERVISOR
        else Thesis.student_id == user.id,
    )
    # Readers retain a shared lock while loading stages so revision and plan agree.
    statement = statement.with_for_update(read=not lock).execution_options(populate_existing=True)
    return await session.scalar(statement)


async def list_theses(session: AsyncSession, user: User, params: PageParams) -> list[Thesis]:
    return list(
        await session.scalars(
            select(Thesis)
            .where(
                Thesis.supervisor_id == user.id
                if user.role == UserRole.SUPERVISOR
                else Thesis.student_id == user.id
            )
            .order_by(Thesis.created_at.desc(), Thesis.id.desc())
            .limit(params.limit)
            .offset(params.offset)
            .with_for_update(read=True)
        )
    )
