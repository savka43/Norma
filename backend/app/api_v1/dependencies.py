from collections.abc import AsyncIterator
from typing import Annotated, cast

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings


def get_settings(request: Request) -> Settings:
    return cast(Settings, request.state.settings)


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    session_factory = cast(async_sessionmaker[AsyncSession], request.state.session_factory)
    async with session_factory() as session:
        yield session


SettingsDep = Annotated[Settings, Depends(get_settings)]
SessionDep = Annotated[AsyncSession, Depends(get_session)]
