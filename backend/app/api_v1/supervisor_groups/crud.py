from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api_v1.supervisor_groups.schemas import PageParams
from app.core.models import GroupMembership, SupervisorGroup, User, UserRole


async def list_groups(
    session: AsyncSession, supervisor_id: UUID, params: PageParams
) -> list[SupervisorGroup]:
    return list(
        await session.scalars(
            select(SupervisorGroup)
            .where(SupervisorGroup.supervisor_id == supervisor_id)
            .order_by(SupervisorGroup.created_at.desc(), SupervisorGroup.id.desc())
            .limit(params.limit)
            .offset(params.offset)
        )
    )


async def find_owned_group(
    session: AsyncSession, group_id: UUID, supervisor_id: UUID
) -> SupervisorGroup | None:
    return await session.scalar(
        select(SupervisorGroup).where(
            SupervisorGroup.id == group_id, SupervisorGroup.supervisor_id == supervisor_id
        )
    )


async def find_student(session: AsyncSession, student_id: UUID) -> User | None:
    return await session.scalar(
        select(User).where(User.id == student_id, User.role == UserRole.STUDENT)
    )


async def list_students(session: AsyncSession, group_id: UUID, params: PageParams) -> list[User]:
    return list(
        await session.scalars(
            select(User)
            .join(GroupMembership, GroupMembership.student_id == User.id)
            .where(GroupMembership.group_id == group_id, User.role == UserRole.STUDENT)
            .order_by(User.full_name, User.id)
            .limit(params.limit)
            .offset(params.offset)
        )
    )
