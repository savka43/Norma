import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Barrier
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from httpx import AsyncClient
from sqlalchemy import delete, update
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.api_v1.documents import crud as document_crud
from app.api_v1.documents.docx_import import DOCX_MEDIA_TYPE
from app.core.config import Settings
from app.core.database import create_engine, create_session_factory
from app.core.models import (
    Document,
    DocumentAsset,
    DocumentEditLease,
    DocumentImport,
    DocumentVersion,
    FormattingTemplate,
    FormattingTemplateVersion,
    GroupMembership,
    SupervisorGroup,
    Thesis,
    User,
    UserRole,
)
from app.main import create_app
from tests.document_helpers import content, parameters
from tests.docx_helpers import docx, paragraph
from tests.integration.actors import Actors, authenticate, make_actors, seed_actors
from tests.integration.alembic_helpers import run_alembic

pytestmark = pytest.mark.integration


@dataclass(frozen=True)
class Workspace:
    actors: Actors
    thesis_id: str
    document_id: str
    template_id: str
    template_version_id: str


@pytest_asyncio.fixture
async def workspace(api_client: AsyncClient, db_session: AsyncSession) -> Workspace:
    actors = make_actors()
    await seed_actors(db_session, actors)
    authenticate(api_client, actors, actors.owner)
    created = await api_client.post(
        "/api/v1/formatting-templates", json={"name": "Шаблон", "parameters": parameters()}
    )
    assert created.status_code == 201, created.text
    template = created.json()
    thesis = await api_client.post(
        "/api/v1/theses",
        json={
            "student_id": str(actors.student.id),
            "title": "Документы ВКР",
            "start_date": "2026-01-01",
            "due_date": "2027-06-30",
        },
    )
    assert thesis.status_code == 201, thesis.text
    thesis_id = thesis.json()["id"]
    authenticate(api_client, actors, actors.student)
    path = f"/api/v1/theses/{thesis_id}/document"
    assert (await api_client.get(path)).status_code == 404
    document = await api_client.post(path, json={"template_version_id": template["version"]["id"]})
    assert document.status_code == 201, document.text
    return Workspace(
        actors,
        thesis_id,
        document.json()["id"],
        template["template"]["id"],
        template["version"]["id"],
    )


def save_payload(
    workspace: Workspace, revision: int = 1, text: str = "Первая версия"
) -> dict[str, object]:
    return {
        "content": content(text),
        "schema_version": 1,
        "template_version_id": workspace.template_version_id,
        "expected_revision": revision,
    }


async def acquire(client: AsyncClient, workspace: Workspace) -> dict[str, str]:
    response = await client.post(f"/api/v1/documents/{workspace.document_id}/edit-lease")
    assert response.status_code == 201, response.text
    assert response.headers["cache-control"] == "no-store"
    return {"X-Edit-Lease": response.json()["lease_id"]}


async def snapshot(
    client: AsyncClient, workspace: Workspace, headers: dict[str, str], revision: int
) -> dict[str, object]:
    response = await client.post(
        f"/api/v1/documents/{workspace.document_id}/versions",
        headers=headers,
        json={"expected_revision": revision, "comment": "Контрольная версия"},
    )
    assert response.status_code == 201, response.text
    return response.json()


async def test_save_snapshot_template_switch_and_restore(
    api_client: AsyncClient, workspace: Workspace
) -> None:
    base = f"/api/v1/documents/{workspace.document_id}"
    initial = (await api_client.get(base)).json()
    assert initial["revision"] == 1 and initial["last_version_number"] == 0
    assert "lease_id" not in initial
    assert (
        await api_client.post(
            f"/api/v1/theses/{workspace.thesis_id}/document",
            json={"template_version_id": workspace.template_version_id},
        )
    ).status_code == 409
    lease = await acquire(api_client, workspace)
    saved = await api_client.put(base, headers=lease, json=save_payload(workspace))
    assert saved.status_code == 200, saved.text
    assert saved.json()["revision"] == 2 and saved.json()["content"] == content("Первая версия")
    first = await snapshot(api_client, workspace, lease, 2)
    assert first["number"] == 1 and first["document_revision"] == 2
    authenticate(api_client, workspace.actors, workspace.actors.owner)
    template_update = await api_client.post(
        f"/api/v1/formatting-templates/{workspace.template_id}/versions",
        json={"expected_version": 1, "parameters": parameters(16)},
    )
    assert template_update.status_code == 201, template_update.text
    latest_id = template_update.json()["id"]
    authenticate(api_client, workspace.actors, workspace.actors.student)
    changed = {**save_payload(workspace, 2, "Новый текст"), "template_version_id": latest_id}
    assert (await api_client.put(base, headers=lease, json=changed)).status_code == 200
    second = await snapshot(api_client, workspace, lease, 3)
    assert second["number"] == 2 and second["template_version_id"] == latest_id
    assert (await api_client.get(f"/api/v1/document-versions/{first['id']}")).json() == first
    restored = await api_client.post(
        f"{base}/restore", headers=lease, json={"version_id": first["id"], "expected_revision": 3}
    )
    assert restored.status_code == 200, restored.text
    result = restored.json()
    assert result["document"]["revision"] == 4
    assert result["document"]["content"] == first["content"]
    assert result["document"]["template_version_id"] == workspace.template_version_id
    assert result["version"]["number"] == 3 and result["version"]["restored_from_id"] == first["id"]
    assert result["version"]["document_revision"] == 4
    assert (await api_client.get(f"/api/v1/document-versions/{first['id']}")).json() == first
    assert (await api_client.get(f"/api/v1/document-versions/{second['id']}")).json() == second
    listing = (await api_client.get(f"{base}/versions")).json()
    assert [item["number"] for item in listing["items"]] == [3, 2, 1]
    assert all("content" not in item for item in listing["items"])
    page = (await api_client.get(f"{base}/versions?limit=1&offset=1")).json()
    assert page["items"] == [listing["items"][1]]
    assert (
        await api_client.get(f"/api/v1/theses/{workspace.thesis_id}/document")
    ).json() == result["document"]


async def test_lease_conflict_renew_release_expiry_and_stale_client(
    api_client: AsyncClient, workspace: Workspace, db_session: AsyncSession
) -> None:
    base = f"/api/v1/documents/{workspace.document_id}"
    lease = await acquire(api_client, workspace)
    assert (await api_client.post(f"{base}/edit-lease")).status_code == 409
    assert (await api_client.post(f"{base}/edit-lease/renew", headers=lease)).status_code == 200
    wrong = {"X-Edit-Lease": str(uuid4())}
    for method, path, payload in (
        ("PUT", base, save_payload(workspace)),
        ("POST", f"{base}/versions", {"expected_revision": 1}),
        ("POST", f"{base}/restore", {"version_id": str(uuid4()), "expected_revision": 1}),
        ("POST", f"{base}/edit-lease/renew", None),
        ("DELETE", f"{base}/edit-lease", None),
    ):
        assert (
            await api_client.request(method, path, headers=wrong, json=payload)
        ).status_code == 409
    now = datetime.now(UTC)
    await db_session.execute(
        update(DocumentEditLease)
        .where(DocumentEditLease.document_id == UUID(workspace.document_id))
        .values(acquired_at=now - timedelta(minutes=5), expires_at=now - timedelta(minutes=1))
    )
    await db_session.commit()
    assert (
        await api_client.put(base, headers=lease, json=save_payload(workspace))
    ).status_code == 409
    assert (await api_client.post(f"{base}/edit-lease/renew", headers=lease)).status_code == 409
    newer = await acquire(api_client, workspace)
    assert newer != lease
    assert (await api_client.delete(f"{base}/edit-lease", headers=lease)).status_code == 409
    assert (
        await api_client.put(base, headers=lease, json=save_payload(workspace))
    ).status_code == 409
    assert (await api_client.delete(f"{base}/edit-lease", headers=newer)).status_code == 204
    assert (await api_client.delete(f"{base}/edit-lease", headers=newer)).status_code == 204
    assert (
        await api_client.put(base, headers=newer, json=save_payload(workspace))
    ).status_code == 409


async def test_stale_revision_and_unknown_restore_are_atomic(
    api_client: AsyncClient, workspace: Workspace
) -> None:
    base = f"/api/v1/documents/{workspace.document_id}"
    lease = await acquire(api_client, workspace)
    version = await snapshot(api_client, workspace, lease, 1)
    assert (
        await api_client.put(base, headers=lease, json=save_payload(workspace))
    ).status_code == 200
    before = (await api_client.get(base)).json()
    assert (
        await api_client.put(base, headers=lease, json=save_payload(workspace))
    ).status_code == 409
    assert (
        await api_client.post(f"{base}/versions", headers=lease, json={"expected_revision": 1})
    ).status_code == 409
    assert (
        await api_client.post(
            f"{base}/restore",
            headers=lease,
            json={"expected_revision": 1, "version_id": version["id"]},
        )
    ).status_code == 409
    assert (
        await api_client.post(
            f"{base}/restore",
            headers=lease,
            json={"expected_revision": 2, "version_id": str(uuid4())},
        )
    ).status_code == 404
    assert (await api_client.get(base)).json() == before
    assert len((await api_client.get(f"{base}/versions")).json()["items"]) == 1


@pytest.mark.parametrize("role", ["guest", "owner", "other", "peer", "free"])
async def test_document_routes_check_role_and_ownership(
    api_client: AsyncClient, workspace: Workspace, role: str
) -> None:
    base = f"/api/v1/documents/{workspace.document_id}"
    lease = await acquire(api_client, workspace)
    version = await snapshot(api_client, workspace, lease, 1)
    actors = workspace.actors
    user = {
        "owner": actors.owner,
        "other": actors.other,
        "peer": actors.peer,
        "free": actors.free,
    }.get(role)
    api_client.cookies.clear()
    if user:
        authenticate(api_client, actors, user)
    read_status = 401 if role == "guest" else (200 if role == "owner" else 404)
    for path in (
        base,
        f"/api/v1/theses/{workspace.thesis_id}/document",
        f"{base}/versions",
        f"/api/v1/document-versions/{version['id']}",
    ):
        result = await api_client.get(path)
        assert result.status_code == read_status, (path, result.text)
        if read_status == 200:
            assert result.headers["cache-control"] == "no-store"
    write_status = 401 if role == "guest" else (403 if role in {"owner", "other"} else 404)
    for method, path, payload in (
        (
            "POST",
            f"/api/v1/theses/{workspace.thesis_id}/document",
            {"template_version_id": workspace.template_version_id},
        ),
        ("PUT", base, save_payload(workspace)),
        ("POST", f"{base}/edit-lease", None),
        ("POST", f"{base}/edit-lease/renew", None),
        ("DELETE", f"{base}/edit-lease", None),
        ("POST", f"{base}/versions", {"expected_revision": 1}),
        ("POST", f"{base}/restore", {"expected_revision": 1, "version_id": version["id"]}),
    ):
        response = await api_client.request(method, path, headers=lease, json=payload)
        assert response.status_code == write_status, (path, response.text)


async def test_csrf_headers_and_missing_resources(
    api_client: AsyncClient, workspace: Workspace
) -> None:
    base = f"/api/v1/documents/{workspace.document_id}"
    lease = await acquire(api_client, workspace)
    for header in ({}, {"X-Edit-Lease": "invalid"}):
        assert (
            await api_client.put(base, headers=header, json=save_payload(workspace))
        ).status_code == 422
    assert (await api_client.get(f"/api/v1/documents/{uuid4()}")).status_code == 404
    assert (await api_client.get(f"/api/v1/document-versions/{uuid4()}")).status_code == 404
    assert (await api_client.post(f"/api/v1/documents/{uuid4()}/edit-lease")).status_code == 404
    del api_client.headers["X-CSRF-Protection"]
    for method, path, payload in (
        ("PUT", base, save_payload(workspace)),
        ("POST", f"{base}/edit-lease", None),
        ("POST", f"{base}/edit-lease/renew", None),
        ("DELETE", f"{base}/edit-lease", None),
        ("POST", f"{base}/versions", {"expected_revision": 1}),
        ("POST", f"{base}/restore", {"expected_revision": 1, "version_id": str(uuid4())}),
        (
            "POST",
            f"/api/v1/theses/{workspace.thesis_id}/document",
            {"template_version_id": workspace.template_version_id},
        ),
    ):
        assert (
            await api_client.request(method, path, headers=lease, json=payload)
        ).status_code == 403


@pytest.mark.parametrize(
    "changes",
    [
        {"schema_version": 5},
        {"schema_version": True},
        {"expected_revision": True},
        {"expected_revision": "1"},
        {"expected_revision": 0},
        {"revision": 2},
        {"content": {}},
    ],
)
async def test_invalid_saves_do_not_change_document(
    api_client: AsyncClient, workspace: Workspace, changes: dict[str, object]
) -> None:
    base = f"/api/v1/documents/{workspace.document_id}"
    lease = await acquire(api_client, workspace)
    before = (await api_client.get(base)).json()
    assert (
        await api_client.put(base, headers=lease, json={**save_payload(workspace), **changes})
    ).status_code == 422
    assert (await api_client.get(base)).json() == before


async def test_template_access_versions_and_foreign_selection(
    api_client: AsyncClient, workspace: Workspace
) -> None:
    actors = workspace.actors
    path = f"/api/v1/formatting-templates/{workspace.template_id}/versions"
    first = (await api_client.get(path)).json()["items"][0]
    version_path = f"/api/v1/formatting-template-versions/{workspace.template_version_id}"
    assert (await api_client.get(version_path)).json() == first
    authenticate(api_client, actors, actors.owner)
    second = await api_client.post(path, json={"expected_version": 1, "parameters": parameters(16)})
    assert second.status_code == 201
    assert second.json()["number"] == 2
    assert (
        await api_client.post(path, json={"expected_version": 1, "parameters": parameters(20)})
    ).status_code == 409
    listing = (await api_client.get(path)).json()["items"]
    assert listing == [second.json(), first]
    authenticate(api_client, actors, actors.other)
    assert (await api_client.get(version_path)).status_code == 404
    assert (await api_client.get(path)).status_code == 404
    assert (
        await api_client.post(path, json={"expected_version": 2, "parameters": parameters()})
    ).status_code == 404
    foreign = await api_client.post(
        "/api/v1/formatting-templates", json={"name": "Чужой", "parameters": parameters()}
    )
    assert foreign.status_code == 201
    assert len((await api_client.get("/api/v1/formatting-templates")).json()["items"]) == 1
    foreign_id = foreign.json()["version"]["id"]
    authenticate(api_client, actors, actors.student)
    assert (await api_client.get(path)).json()["items"] == listing
    assert len((await api_client.get("/api/v1/formatting-templates")).json()["items"]) == 1
    assert (
        await api_client.post(
            "/api/v1/formatting-templates", json={"name": "Нельзя", "parameters": parameters()}
        )
    ).status_code == 403
    assert (
        await api_client.post(path, json={"expected_version": 2, "parameters": parameters()})
    ).status_code == 403
    lease = await acquire(api_client, workspace)
    base = f"/api/v1/documents/{workspace.document_id}"
    before = (await api_client.get(base)).json()
    assert (
        await api_client.put(
            base, headers=lease, json={**save_payload(workspace), "template_version_id": foreign_id}
        )
    ).status_code == 404
    assert (await api_client.get(base)).json() == before
    authenticate(api_client, actors, actors.free)
    assert (await api_client.get(version_path)).status_code == 404
    assert (await api_client.get("/api/v1/formatting-templates")).json()["items"] == []
    assert (await api_client.get(path)).status_code == 404
    api_client.cookies.clear()
    assert (await api_client.get(version_path)).status_code == 401


async def test_restore_rejects_snapshot_from_another_document(
    api_client: AsyncClient, workspace: Workspace
) -> None:
    lease = await acquire(api_client, workspace)
    version = await snapshot(api_client, workspace, lease, 1)
    actors = workspace.actors
    authenticate(api_client, actors, actors.owner)
    created = await api_client.post(
        "/api/v1/theses",
        json={
            "student_id": str(actors.peer.id),
            "title": "Вторая",
            "start_date": "2026-01-01",
            "due_date": "2027-01-01",
        },
    )
    assert created.status_code == 201
    authenticate(api_client, actors, actors.peer)
    other = await api_client.post(
        f"/api/v1/theses/{created.json()['id']}/document",
        json={"template_version_id": workspace.template_version_id},
    )
    assert other.status_code == 201
    other_workspace = Workspace(
        actors,
        created.json()["id"],
        other.json()["id"],
        workspace.template_id,
        workspace.template_version_id,
    )
    other_lease = await acquire(api_client, other_workspace)
    response = await api_client.post(
        f"/api/v1/documents/{other_workspace.document_id}/restore",
        headers=other_lease,
        json={"version_id": version["id"], "expected_revision": 1},
    )
    assert response.status_code == 404
    assert (
        await api_client.get(f"/api/v1/documents/{other_workspace.document_id}")
    ).json() == other.json()


async def test_snapshot_updates_are_rejected_by_database(
    api_client: AsyncClient, workspace: Workspace, db_session: AsyncSession
) -> None:
    from sqlalchemy.exc import IntegrityError

    lease = await acquire(api_client, workspace)
    version = await snapshot(api_client, workspace, lease, 1)
    for statement in (
        update(DocumentVersion)
        .where(DocumentVersion.id == UUID(str(version["id"])))
        .values(content=content("Подмена")),
        update(DocumentVersion)
        .where(DocumentVersion.id == UUID(str(version["id"])))
        .values(comment="Подмена"),
        update(FormattingTemplateVersion)
        .where(FormattingTemplateVersion.id == UUID(workspace.template_version_id))
        .values(parameters=parameters(20)),
    ):
        with pytest.raises(IntegrityError, match="immutable"):
            async with db_session.begin_nested():
                await db_session.execute(statement)
    assert (await api_client.get(f"/api/v1/document-versions/{version['id']}")).json() == version


async def test_unstorable_text_is_rejected_before_database_write(
    api_client: AsyncClient, workspace: Workspace
) -> None:
    lease = await acquire(api_client, workspace)
    response = await api_client.post(
        f"/api/v1/documents/{workspace.document_id}/versions",
        headers=lease,
        json={"expected_revision": 1, "comment": "invalid\x00comment"},
    )
    assert response.status_code == 422
    authenticate(api_client, workspace.actors, workspace.actors.owner)
    response = await api_client.post(
        "/api/v1/formatting-templates", json={"name": "invalid\x00name", "parameters": parameters()}
    )
    assert response.status_code == 422


async def test_real_lexical_content_survives_http_and_snapshot(
    api_client: AsyncClient, workspace: Workspace
) -> None:
    original = json.loads((Path(__file__).parents[1] / "fixtures/lexical-0.53.0.json").read_text())
    lease = await acquire(api_client, workspace)
    base = f"/api/v1/documents/{workspace.document_id}"
    saved = await api_client.put(
        base, headers=lease, json={**save_payload(workspace), "content": original}
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["content"] == original
    assert (await api_client.get(base)).json()["content"] == original
    version = await snapshot(api_client, workspace, lease, 2)
    assert version["content"] == original
    assert (await api_client.get(f"/api/v1/document-versions/{version['id']}")).json()[
        "content"
    ] == original


@pytest.mark.parametrize(
    "query", ["limit=0", "limit=101", "offset=-1", f"offset={2**63}", "extra=1"]
)
async def test_history_and_template_pagination_validation(
    api_client: AsyncClient, workspace: Workspace, query: str
) -> None:
    for path in (
        f"/api/v1/documents/{workspace.document_id}/versions",
        "/api/v1/formatting-templates",
        f"/api/v1/formatting-templates/{workspace.template_id}/versions",
    ):
        assert (await api_client.get(f"{path}?{query}")).status_code == 422


@pytest.mark.parametrize(
    "operation",
    [
        "document",
        "lease",
        "save",
        "snapshots",
        "save_restore",
        "template",
        "import",
        "import_save",
        "import_restore",
        "format",
        "format_save",
        "format_restore",
    ],
)
def test_concurrent_document_operations(
    migrated_database: None,
    integration_settings: Settings,
    operation: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    actors = make_actors()
    thesis_id, template_id, template_version_id, document_id, lease_id, snapshot_id = (
        uuid4() for _ in range(6)
    )
    student_id = actors.student.id

    async def prepare_or_cleanup(*, cleanup: bool) -> None:
        engine = create_engine(integration_settings)
        try:
            async with create_session_factory(engine)() as session:
                if cleanup:
                    scope = DocumentVersion.document_id == document_id
                    await session.execute(
                        delete(DocumentAsset).where(DocumentAsset.document_id == document_id)
                    )
                    await session.execute(
                        delete(DocumentImport).where(DocumentImport.document_id == document_id)
                    )
                    await session.execute(
                        delete(DocumentEditLease).where(
                            DocumentEditLease.document_id == document_id
                        )
                    )
                    await session.execute(
                        delete(DocumentVersion).where(
                            scope, DocumentVersion.restored_from_id.is_not(None)
                        )
                    )
                    await session.execute(delete(DocumentVersion).where(scope))
                    await session.execute(delete(Document).where(Document.thesis_id == thesis_id))
                    await session.execute(delete(Thesis).where(Thesis.id == thesis_id))
                    await session.execute(
                        delete(FormattingTemplateVersion).where(
                            FormattingTemplateVersion.template_id == template_id
                        )
                    )
                    await session.execute(
                        delete(FormattingTemplate).where(FormattingTemplate.id == template_id)
                    )
                    await session.execute(
                        delete(GroupMembership).where(
                            GroupMembership.student_id.in_([user.id for user in actors.users])
                        )
                    )
                    await session.execute(
                        delete(SupervisorGroup).where(
                            SupervisorGroup.id.in_([actors.group.id, actors.foreign_group.id])
                        )
                    )
                    await session.execute(
                        delete(User).where(User.id.in_([user.id for user in actors.users]))
                    )
                else:
                    await seed_actors(session, actors)
                    session.add(
                        Thesis(
                            id=thesis_id,
                            student_id=student_id,
                            supervisor_id=actors.owner.id,
                            title="Гонки документов",
                            start_date=datetime(2026, 1, 1).date(),
                            due_date=datetime(2027, 6, 30).date(),
                        )
                    )
                    session.add(
                        FormattingTemplate(
                            id=template_id, supervisor_id=actors.owner.id, name="Тест"
                        )
                    )
                    await session.flush()
                    session.add(
                        FormattingTemplateVersion(
                            id=template_version_id,
                            template_id=template_id,
                            number=1,
                            parameters=parameters(),
                        )
                    )
                    await session.flush()
                    if operation != "document":
                        session.add(
                            Document(
                                id=document_id,
                                thesis_id=thesis_id,
                                content=content("Исходный"),
                                template_version_id=template_version_id,
                                last_version_number=1
                                if operation in {"save_restore", "import_restore", "format_restore"}
                                else 0,
                                schema_version=3 if operation == "format" else 1,
                            )
                        )
                        await session.flush()
                    if operation in {
                        "save",
                        "snapshots",
                        "save_restore",
                        "import",
                        "import_save",
                        "import_restore",
                        "format",
                        "format_save",
                        "format_restore",
                    }:
                        now = datetime.now(UTC)
                        session.add(
                            DocumentEditLease(
                                document_id=document_id,
                                lease_id=lease_id,
                                holder_id=student_id,
                                acquired_at=now,
                                expires_at=now + timedelta(minutes=5),
                            )
                        )
                    if operation in {"save_restore", "import_restore", "format_restore"}:
                        session.add(
                            DocumentVersion(
                                id=snapshot_id,
                                document_id=document_id,
                                number=1,
                                document_revision=1,
                                schema_version=1,
                                content=content("Исходный"),
                                template_version_id=template_version_id,
                                created_by_id=student_id,
                            )
                        )
                await session.commit()
        finally:
            await engine.dispose()

    try:
        asyncio.run(prepare_or_cleanup(cleanup=False))
        if operation.startswith(("import", "format")):
            original_find = document_crud.find_document
            lock_barrier = Barrier(2)

            async def synchronized_find(
                session: AsyncSession, requested_id: UUID, user: User, *, lock: bool = False
            ) -> Document | None:
                if lock and requested_id == document_id and user.role == UserRole.STUDENT:
                    await run_in_threadpool(lock_barrier.wait, 10)
                return await original_find(session, requested_id, user, lock=lock)

            monkeypatch.setattr(document_crud, "find_document", synchronized_find)
        headers = {"X-CSRF-Protection": "1", "X-Edit-Lease": str(lease_id)}
        with (
            TestClient(create_app(integration_settings), headers=headers) as first,
            TestClient(create_app(integration_settings), headers=headers) as second,
        ):
            for client in (first, second):
                authenticate(
                    client, actors, actors.owner if operation == "template" else actors.student
                )
            barrier = Barrier(2)

            def write(client: TestClient, index: int) -> tuple[int, int]:
                barrier.wait(timeout=10)
                base = f"/api/v1/documents/{document_id}"
                if operation == "document":
                    response = client.post(
                        f"/api/v1/theses/{thesis_id}/document",
                        json={"template_version_id": str(template_version_id)},
                    )
                elif operation == "lease":
                    response = client.post(f"{base}/edit-lease")
                elif operation == "template":
                    response = client.post(
                        f"/api/v1/formatting-templates/{template_id}/versions",
                        json={"expected_version": 1, "parameters": parameters(16 + index)},
                    )
                elif operation == "snapshots":
                    response = client.post(f"{base}/versions", json={"expected_revision": 1})
                elif operation.startswith("import") and (index == 0 or operation == "import"):
                    response = client.post(
                        f"{base}/import?expected_revision=1&confirm_replace=true",
                        headers={"Content-Type": DOCX_MEDIA_TYPE},
                        content=docx(paragraph(f"Импорт {index}")),
                    )
                elif operation.startswith("format") and (index == 0 or operation == "format"):
                    response = client.post(
                        f"{base}/apply-formatting",
                        json={
                            "expected_revision": 1,
                            "template_version_id": str(template_version_id),
                            "confirm_apply": True,
                        },
                    )
                elif (
                    operation in {"save_restore", "import_restore", "format_restore"} and index == 1
                ):
                    response = client.post(
                        f"{base}/restore",
                        json={"expected_revision": 1, "version_id": str(snapshot_id)},
                    )
                else:
                    response = client.put(
                        base,
                        json={
                            "expected_revision": 1,
                            "schema_version": 1,
                            "content": content(f"Текст {index}"),
                            "template_version_id": str(template_version_id),
                        },
                    )
                return response.status_code, index

            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = [
                    pool.submit(write, client, index)
                    for index, client in enumerate((first, second))
                ]
                results = [future.result(timeout=20) for future in futures]
            success = next(code for code, _ in results if code in (200, 201))
            assert sorted(code for code, _ in results) == (
                [201, 201] if operation == "snapshots" else [success, 409]
            )
            winner = next(index for code, index in results if code == success)
            if operation == "template":
                versions = first.get(f"/api/v1/formatting-templates/{template_id}/versions").json()[
                    "items"
                ]
                assert [item["number"] for item in versions] == [2, 1]
                assert versions[0]["parameters"]["body"]["font_size_pt"] == 16 + winner
                assert versions[1]["parameters"]["body"]["font_size_pt"] == 14
            elif operation == "document":
                assert first.get(f"/api/v1/theses/{thesis_id}/document").json()["revision"] == 1
            else:
                base = f"/api/v1/documents/{document_id}"
                document = first.get(base).json()
                versions = first.get(f"{base}/versions").json()["items"]
                if operation.startswith("format"):
                    assert document["revision"] == 2
                    applied = operation == "format" or winner == 0
                    assert len(versions) == (
                        (3 if operation == "format_restore" else 2)
                        if applied
                        else (2 if operation == "format_restore" else 0)
                    )
                    assert document["content"] == content(
                        "Исходный" if applied or operation == "format_restore" else "Текст 1"
                    )
                    if operation == "format":
                        with pytest.raises(AssertionError, match="Cannot downgrade"):
                            run_alembic(integration_settings, "downgrade", "0007_docx_import")
                        assert first.get(base).json() == document
                        run_alembic(integration_settings, "check")
                elif operation.startswith("import"):
                    assert document["revision"] == 2
                    imports = first.get(f"{base}/imports").json()["items"]
                    imported = operation == "import" or winner == 0
                    assert len(imports) == int(imported)
                    if imported:
                        assert document["schema_version"] == 2
                        assert f"Импорт {winner}" in json.dumps(
                            document["content"], ensure_ascii=False
                        )
                        assert len(versions) == (3 if operation == "import_restore" else 2)
                        old = first.get(
                            f"/api/v1/document-versions/{imports[0]['previous_version_id']}"
                        ).json()
                        assert old["content"] == content("Исходный")
                        if operation == "import":
                            with pytest.raises(AssertionError, match="Cannot downgrade"):
                                run_alembic(integration_settings, "downgrade", "0006_documents")
                            assert first.get(base).json() == document
                            run_alembic(integration_settings, "current")
                    else:
                        expected = content(
                            "Исходный" if operation == "import_restore" else "Текст 1"
                        )
                        assert document["content"] == expected
                        assert len(versions) == (2 if operation == "import_restore" else 0)
                elif operation in {"save", "save_restore"}:
                    assert document["revision"] == 2
                    expected = (
                        content("Исходный")
                        if operation == "save_restore" and winner == 1
                        else content(f"Текст {winner}")
                    )
                    assert document["content"] == expected
                    if operation == "save_restore":
                        assert len(versions) == (2 if winner == 1 else 1)
                        assert first.get(f"/api/v1/document-versions/{snapshot_id}").json()[
                            "content"
                        ] == content("Исходный")
                elif operation == "snapshots":
                    assert document["revision"] == 1 and document["last_version_number"] == 2
                    assert [item["number"] for item in versions] == [2, 1]
    finally:
        asyncio.run(prepare_or_cleanup(cleanup=True))
