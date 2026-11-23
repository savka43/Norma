import asyncio

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import text

from app.core.config import Settings
from app.core.database import create_engine
from app.main import create_app
from tests.integration.alembic_helpers import run_alembic

pytestmark = pytest.mark.integration


def test_readiness_with_real_postgresql(integration_settings: Settings) -> None:
    with TestClient(create_app(integration_settings)) as client:
        response = client.get("/api/v1/health/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}


def test_readiness_with_invalid_database_credentials(integration_settings: Settings) -> None:
    invalid_settings = integration_settings.model_copy(
        update={"database_password": SecretStr("invalid-test-password")}
    )
    with TestClient(create_app(invalid_settings)) as client:
        response = client.get("/api/v1/health/ready")
    assert response.status_code == 503
    assert response.json() == {"detail": "Database is unavailable"}


def test_migration_round_trip(integration_settings: Settings) -> None:
    async def database_state() -> tuple[str | None, set[str], list[str]]:
        engine = create_engine(integration_settings)
        try:
            async with engine.connect() as connection:
                revision = await connection.scalar(text("SELECT version_num FROM alembic_version"))
                tables = await connection.scalars(
                    text(
                        "SELECT tablename FROM pg_tables WHERE schemaname = 'public' "
                        "AND tablename IN ('users', 'auth_sessions', "
                        "'supervisor_groups', 'group_memberships', "
                        "'theses', 'thesis_stages', 'stage_events', "
                        "'documents', 'document_edit_leases', 'document_versions', "
                        "'formatting_templates', 'formatting_template_versions', "
                        "'document_imports', 'document_assets', 'stage_submissions', "
                        "'comments', 'comment_events', 'plagiarism_checks')"
                    )
                )
                roles = await connection.scalars(
                    text(
                        "SELECT enumlabel FROM pg_enum "
                        "JOIN pg_type ON pg_enum.enumtypid = pg_type.oid "
                        "WHERE typname = 'user_role' ORDER BY enumsortorder"
                    )
                )
                return revision, set(tables), list(roles)
        finally:
            await engine.dispose()

    run_alembic(integration_settings, "upgrade", "head")
    assert asyncio.run(database_state()) == (
        "0011_stage_chapters",
        {
            "users",
            "auth_sessions",
            "supervisor_groups",
            "group_memberships",
            "theses",
            "thesis_stages",
            "stage_events",
            "documents",
            "document_edit_leases",
            "document_versions",
            "formatting_templates",
            "formatting_template_versions",
            "document_imports",
            "document_assets",
            "stage_submissions",
            "comments",
            "comment_events",
            "plagiarism_checks",
        },
        ["student", "supervisor"],
    )
    run_alembic(integration_settings, "check")
    run_alembic(integration_settings, "downgrade", "0006_documents")
    revision, tables, roles = asyncio.run(database_state())
    assert revision == "0006_documents"
    assert {"documents", "document_versions", "formatting_template_versions"} <= tables
    assert not {"document_imports", "document_assets"} & tables
    assert roles == ["student", "supervisor"]
    run_alembic(integration_settings, "upgrade", "head")
    run_alembic(integration_settings, "downgrade", "0005_theses_stages")
    assert asyncio.run(database_state()) == (
        "0005_theses_stages",
        {
            "users",
            "auth_sessions",
            "supervisor_groups",
            "group_memberships",
            "theses",
            "thesis_stages",
            "stage_events",
        },
        ["student", "supervisor"],
    )
    run_alembic(integration_settings, "upgrade", "head")
    run_alembic(integration_settings, "downgrade", "0004_supervisor_groups")
    assert asyncio.run(database_state()) == (
        "0004_supervisor_groups",
        {"users", "auth_sessions", "supervisor_groups", "group_memberships"},
        ["student", "supervisor"],
    )
    run_alembic(integration_settings, "upgrade", "head")
    run_alembic(integration_settings, "downgrade", "0003_auth_sessions")
    assert asyncio.run(database_state()) == (
        "0003_auth_sessions",
        {"users", "auth_sessions"},
        ["student", "supervisor"],
    )
    run_alembic(integration_settings, "upgrade", "head")
    run_alembic(integration_settings, "downgrade", "0002_users")
    assert asyncio.run(database_state()) == ("0002_users", {"users"}, ["student", "supervisor"])
    run_alembic(integration_settings, "upgrade", "head")
    run_alembic(integration_settings, "downgrade", "0001_api_foundation")
    assert asyncio.run(database_state()) == ("0001_api_foundation", set(), [])
    run_alembic(integration_settings, "upgrade", "head")
    run_alembic(integration_settings, "downgrade", "base")
    assert asyncio.run(database_state()) == (None, set(), [])
    run_alembic(integration_settings, "upgrade", "head")
    run_alembic(integration_settings, "check")
