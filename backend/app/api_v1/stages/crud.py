from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api_v1.supervisor_groups.schemas import PageParams
from app.core.models import GroupMembership, StageEvent, Thesis, ThesisStage, User, UserRole


async def list_stages(session: AsyncSession, thesis_ids: list[UUID]) -> list[ThesisStage]:
    if not thesis_ids:
        return []
    return list(
        await session.scalars(
            select(ThesisStage)
            .where(ThesisStage.thesis_id.in_(thesis_ids))
            .order_by(ThesisStage.thesis_id, ThesisStage.position)
            .execution_options(populate_existing=True)
        )
    )


async def find_accessible_stage(
    session: AsyncSession, stage_id: UUID, user: User
) -> ThesisStage | None:
    return await session.scalar(
        select(ThesisStage)
        .join(Thesis, Thesis.id == ThesisStage.thesis_id)
        .where(
            ThesisStage.id == stage_id,
            Thesis.supervisor_id == user.id
            if user.role == UserRole.SUPERVISOR
            else Thesis.student_id == user.id,
        )
    )


async def list_history(
    session: AsyncSession, stage_id: UUID, params: PageParams
) -> list[StageEvent]:
    return list(
        await session.scalars(
            select(StageEvent)
            .where(StageEvent.stage_id == stage_id)
            .order_by(StageEvent.thesis_revision, StageEvent.id)
            .limit(params.limit)
            .offset(params.offset)
        )
    )


async def list_group_theses(
    session: AsyncSession, group_id: UUID, params: PageParams
) -> list[tuple[User, Thesis | None]]:
    students = list(
        await session.scalars(
            select(User)
            .join(GroupMembership, GroupMembership.student_id == User.id)
            .where(GroupMembership.group_id == group_id)
            .order_by(User.full_name, User.id)
            .limit(params.limit)
            .offset(params.offset)
        )
    )
    if not students:
        return []
    theses = await session.scalars(
        select(Thesis)
        .where(Thesis.student_id.in_([student.id for student in students]))
        .order_by(Thesis.id)
        .with_for_update(read=True)
        .execution_options(populate_existing=True)
    )
    by_student = {thesis.student_id: thesis for thesis in theses}
    return [(student, by_student.get(student.id)) for student in students]
