import asyncio
import logging
import signal

from sqlalchemy.exc import SQLAlchemyError

from app.api_v1.plagiarism.client import AntiplagiatClient
from app.api_v1.plagiarism.service import process_due
from app.core.config import load_settings
from app.core.database import create_engine, create_session_factory

logger = logging.getLogger(__name__)


async def run() -> None:
    settings = load_settings()
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(signum, stop.set)
    if not settings.plagiarism_enabled:
        logger.info("Antiplagiat worker is disabled")
        await stop.wait()
        return
    engine = create_engine(settings)
    sessions = create_session_factory(engine)
    client = AntiplagiatClient(settings)
    logger.info("Antiplagiat worker is ready")
    try:
        while not stop.is_set():
            delay = 1
            try:
                if await process_due(sessions, settings, client):
                    continue
            except SQLAlchemyError as exc:
                logger.warning("Antiplagiat worker database error: %s", type(exc).__name__)
                delay = 5
            try:
                await asyncio.wait_for(stop.wait(), timeout=delay)
            except TimeoutError:
                pass
    finally:
        await engine.dispose()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run())
