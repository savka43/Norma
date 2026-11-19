from fastapi import APIRouter, Depends, HTTPException, Response, status

from app.api_v1.auth import service
from app.api_v1.auth.dependencies import (
    CurrentUserDep,
    SessionTokenDep,
    require_csrf_header,
)
from app.api_v1.auth.schemas import LoginRequest, StudentRegistration, UserResponse
from app.api_v1.dependencies import SessionDep, SettingsDep
from app.core.security import SESSION_COOKIE_NAME, SESSION_COOKIE_PATH

router = APIRouter(prefix="/auth", tags=["auth"], dependencies=[Depends(require_csrf_header)])


@router.post(
    "/register",
    status_code=status.HTTP_201_CREATED,
    responses={409: {"description": "Email занят"}},
)
async def register(data: StudentRegistration, session: SessionDep) -> UserResponse:
    try:
        user = await service.register_student(session, data)
    except service.EmailAlreadyExistsError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, "Email already registered") from exc
    return UserResponse.model_validate(user)


@router.post("/login", responses={401: {"description": "Неверные учётные данные"}})
async def login(
    data: LoginRequest,
    session: SessionDep,
    settings: SettingsDep,
    response: Response,
    token: SessionTokenDep,
) -> UserResponse:
    result = await service.login(
        session, settings, str(data.email), data.password.get_secret_value(), token
    )
    if result is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid email or password")
    user, new_token = result
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=new_token,
        max_age=settings.session_lifetime_seconds,
        path=SESSION_COOKIE_PATH,
        secure=settings.session_cookie_secure,
        httponly=True,
        samesite="lax",
    )
    response.headers["Cache-Control"] = "no-store"
    return UserResponse.model_validate(user)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(session: SessionDep, settings: SettingsDep, token: SessionTokenDep) -> Response:
    await service.logout(session, token)
    response = Response(
        status_code=status.HTTP_204_NO_CONTENT, headers={"Cache-Control": "no-store"}
    )
    response.delete_cookie(
        key=SESSION_COOKIE_NAME,
        path=SESSION_COOKIE_PATH,
        secure=settings.session_cookie_secure,
        httponly=True,
        samesite="lax",
    )
    return response


@router.get("/me", responses={401: {"description": "Требуется вход"}})
async def me(user: CurrentUserDep, response: Response) -> UserResponse:
    response.headers["Cache-Control"] = "no-store"
    return UserResponse.model_validate(user)
