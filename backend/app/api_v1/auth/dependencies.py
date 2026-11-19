from datetime import UTC, datetime
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request, status
from fastapi.security import APIKeyCookie

from app.api_v1.auth import crud
from app.api_v1.dependencies import SessionDep
from app.core.models import User, UserRole
from app.core.security import SESSION_COOKIE_NAME, session_token_hash

_session_cookie = APIKeyCookie(name=SESSION_COOKIE_NAME, auto_error=False)
SessionTokenDep = Annotated[str | None, Depends(_session_cookie)]


def require_csrf_header(
    request: Request,
    x_csrf_protection: Annotated[str | None, Header()] = None,
) -> None:
    # Custom headers require a browser preflight. This API deliberately has no CORS allowance.
    if request.method not in {"GET", "HEAD", "OPTIONS"} and x_csrf_protection != "1":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "X-CSRF-Protection: 1 header is required")


async def get_current_user(
    session: SessionDep,
    token: SessionTokenDep,
    _csrf: Annotated[None, Depends(require_csrf_header)],
) -> User:
    token_hash = session_token_hash(token)
    if token_hash is not None:
        user = await crud.find_session_user(session, token_hash, datetime.now(UTC))
        if user is not None:
            return user
    raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Authentication required")


CurrentUserDep = Annotated[User, Depends(get_current_user)]


def get_supervisor(user: CurrentUserDep) -> User:
    if user.role != UserRole.SUPERVISOR:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Supervisor role required")
    return user


SupervisorDep = Annotated[User, Depends(get_supervisor)]
