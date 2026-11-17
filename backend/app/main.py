from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api_v1.router import router
from app.core.config import Settings, load_settings
from app.core.database import create_engine, create_session_factory


def create_app(settings: Settings | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncGenerator[dict[str, object], None]:
        configuration = settings if settings is not None else load_settings()
        engine = create_engine(configuration)
        try:
            yield {
                "settings": configuration,
                "session_factory": create_session_factory(engine),
            }
        finally:
            await engine.dispose()

    application = FastAPI(title="Норма API", version="0.1.0", lifespan=lifespan)
    application.include_router(router)
    return application


app = create_app()
