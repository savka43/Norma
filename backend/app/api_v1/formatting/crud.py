from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api_v1.supervisor_groups.schemas import PageParams
from app.core.models import (
    FormattingTemplate,
    FormattingTemplateVersion,
    GroupMembership,
    SupervisorGroup,
    User,
    UserRole,
)


async def accessible_supervisor_id(session: AsyncSession, user: User) -> UUID | None:
    if user.role == UserRole.SUPERVISOR:
        return user.id
    return await session.scalar(
        select(SupervisorGroup.supervisor_id)
        .join(GroupMembership, GroupMembership.group_id == SupervisorGroup.id)
        .where(GroupMembership.student_id == user.id)
    )


async def find_template(
    session: AsyncSession, template_id: UUID, supervisor_id: UUID | None, *, lock: bool = False
) -> FormattingTemplate | None:
    statement = select(FormattingTemplate).where(
        FormattingTemplate.id == template_id, FormattingTemplate.supervisor_id == supervisor_id
    )
    if lock:
        statement = statement.with_for_update().execution_options(populate_existing=True)
    return await session.scalar(statement)


async def list_templates(
    session: AsyncSession, supervisor_id: UUID | None, params: PageParams
) -> list[FormattingTemplate]:
    return list(
        await session.scalars(
            select(FormattingTemplate)
            .where(FormattingTemplate.supervisor_id == supervisor_id)
            .order_by(FormattingTemplate.created_at.desc(), FormattingTemplate.id.desc())
            .limit(params.limit)
            .offset(params.offset)
        )
    )


async def list_versions(
    session: AsyncSession, template_id: UUID, params: PageParams
) -> list[FormattingTemplateVersion]:
    return list(
        await session.scalars(
            select(FormattingTemplateVersion)
            .where(FormattingTemplateVersion.template_id == template_id)
            .order_by(FormattingTemplateVersion.number.desc())
            .limit(params.limit)
            .offset(params.offset)
        )
    )


async def find_version(
    session: AsyncSession, version_id: UUID, supervisor_id: UUID | None
) -> FormattingTemplateVersion | None:
    return await session.scalar(
        select(FormattingTemplateVersion)
        .join(FormattingTemplate, FormattingTemplate.id == FormattingTemplateVersion.template_id)
        .where(
            FormattingTemplateVersion.id == version_id,
            FormattingTemplate.supervisor_id == supervisor_id,
        )
    )
