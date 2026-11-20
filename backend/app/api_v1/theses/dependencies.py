from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, status

from app.api_v1.auth.dependencies import CurrentUserDep, SupervisorDep
from app.api_v1.dependencies import SessionDep
from app.api_v1.theses.crud import find_accessible_thesis
from app.core.models import Thesis


async def get_accessible_thesis(
    thesis_id: UUID, user: CurrentUserDep, session: SessionDep
) -> Thesis:
    thesis = await find_accessible_thesis(session, thesis_id, user)
    if thesis is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Thesis not found")
    return thesis


async def get_locked_owned_thesis(
    thesis_id: UUID, supervisor: SupervisorDep, session: SessionDep
) -> Thesis:
    thesis = await find_accessible_thesis(session, thesis_id, supervisor, lock=True)
    if thesis is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Thesis not found")
    return thesis


AccessibleThesisDep = Annotated[Thesis, Depends(get_accessible_thesis)]
LockedOwnedThesisDep = Annotated[Thesis, Depends(get_locked_owned_thesis)]
