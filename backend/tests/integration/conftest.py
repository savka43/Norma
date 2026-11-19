from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.api_v1.dependencies import get_session, get_settings
from app.core.config import Settings
from app.core.database import create_engine
from app.main import create_app
from tests.integration.alembic_helpers import run_alembic


@pytest.fixture(scope="session")
def migrated_database(integration_settings: Settings) -> None:
    run_alembic(integration_settings, "upgrade", "head")


@pytest_asyncio.fixture
async def db_session(
    migrated_database: None, integration_settings: Settings
) -> AsyncIterator[AsyncSession]:
    engine = create_engine(integration_settings)
    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            try:
                async with AsyncSession(
                    bind=connection,
                    expire_on_commit=False,
                    join_transaction_mode="create_savepoint",
                ) as session:
                    yield session
            finally:
                await transaction.rollback()
    finally:
        await engine.dispose()


@pytest.fixture
def api_app(db_session: AsyncSession, integration_settings: Settings) -> FastAPI:
    application = create_app(integration_settings)

    async def override_session() -> AsyncIterator[AsyncSession]:
        yield db_session

    application.dependency_overrides[get_session] = override_session
    application.dependency_overrides[get_settings] = lambda: integration_settings
    return application


@pytest_asyncio.fixture
async def api_client(api_app: FastAPI) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=api_app),
        base_url="http://testserver",
        headers={"X-CSRF-Protection": "1"},
    ) as client:
        yield client
