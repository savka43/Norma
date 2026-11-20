from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException

from app.api_v1.auth.dependencies import CurrentUserDep, SupervisorDep
from app.api_v1.dependencies import SessionDep
from app.api_v1.formatting import crud
from app.core.models import FormattingTemplate


async def get_accessible_template(
    template_id: UUID, user: CurrentUserDep, session: SessionDep
) -> FormattingTemplate:
    owner_id = await crud.accessible_supervisor_id(session, user)
    template = await crud.find_template(session, template_id, owner_id)
    if template is None:
        raise HTTPException(404, "Template not found")
    return template


async def get_locked_owned_template(
    template_id: UUID, supervisor: SupervisorDep, session: SessionDep
) -> FormattingTemplate:
    template = await crud.find_template(session, template_id, supervisor.id, lock=True)
    if template is None:
        raise HTTPException(404, "Template not found")
    return template


AccessibleTemplateDep = Annotated[FormattingTemplate, Depends(get_accessible_template)]
LockedOwnedTemplateDep = Annotated[FormattingTemplate, Depends(get_locked_owned_template)]
