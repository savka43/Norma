FROM ghcr.io/astral-sh/uv:0.11.32 AS uv
FROM python:3.12-slim

COPY --from=uv /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --locked --no-dev
COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./

RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin norma
USER norma
EXPOSE 8000
CMD ["fastapi", "run", "--host", "0.0.0.0", "--port", "8000"]
