from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, status

from app.api_v1.auth.dependencies import SupervisorDep
from app.api_v1.dependencies import SessionDep
from app.api_v1.supervisor_groups.crud import find_owned_group
from app.core.models import SupervisorGroup


async def get_owned_group(
    group_id: UUID, session: SessionDep, supervisor: SupervisorDep
) -> SupervisorGroup:
    group = await find_owned_group(session, group_id, supervisor.id)
    if group is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Group not found")
    return group


OwnedGroupDep = Annotated[SupervisorGroup, Depends(get_owned_group)]
