import os
import subprocess
import sys
from pathlib import Path

from app.core.config import Settings

BACKEND_ROOT = Path(__file__).resolve().parents[2]


def run_alembic(settings: Settings, *arguments: str) -> None:
    environment = dict(os.environ)
    environment.update(
        NORMA_DATABASE_HOST=settings.database_host,
        NORMA_DATABASE_PORT=str(settings.database_port),
        NORMA_DATABASE_NAME=settings.database_name,
        NORMA_DATABASE_USER=settings.database_user,
        NORMA_DATABASE_PASSWORD=settings.database_password.get_secret_value(),
    )
    result = subprocess.run(
        [sys.executable, "-m", "alembic", *arguments],
        cwd=BACKEND_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
