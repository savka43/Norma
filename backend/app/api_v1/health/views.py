import asyncio

from asyncpg.exceptions import PostgresError
from fastapi import APIRouter, HTTPException, status
from sqlalchemy.exc import SQLAlchemyError

from app.api_v1.dependencies import SessionDep, SettingsDep
from app.api_v1.health.crud import check_database
from app.api_v1.health.schemas import HealthResponse, ReadinessResponse

router = APIRouter(prefix="/health", tags=["health"])


@router.get("", summary="Проверка работоспособности API")
async def health() -> HealthResponse:
    return HealthResponse()


@router.get(
    "/ready",
    summary="Проверка доступности PostgreSQL",
    responses={503: {"description": "База данных недоступна"}},
)
async def readiness(session: SessionDep, settings: SettingsDep) -> ReadinessResponse:
    try:
        async with asyncio.timeout(settings.readiness_timeout_seconds):
            await check_database(session)
    except (SQLAlchemyError, PostgresError, OSError, TimeoutError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database is unavailable",
        ) from exc
    return ReadinessResponse()
