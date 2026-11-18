from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.database import create_engine
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
