from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api_v1.documents.docx_import import DOCX_MEDIA_TYPE, MAX_UPLOAD_BYTES
from app.api_v1.documents.lexical import LexicalContent, content_nodes
from app.core.models import DocumentAsset, DocumentEditLease, DocumentImport, DocumentVersion
from tests.docx_helpers import docx, image_docx, paragraph
from tests.integration.actors import authenticate
from tests.integration.test_documents import Workspace, acquire, save_payload
from tests.integration.test_documents import workspace as workspace

pytestmark = pytest.mark.integration


async def test_import_source_versions_assets_save_and_restore(
    api_client: AsyncClient,
    workspace: Workspace,
) -> None:
    base = f"/api/v1/documents/{workspace.document_id}"
    original = (await api_client.get(base)).json()
    lease = await acquire(api_client, workspace)
    source = image_docx()
    response = await api_client.post(
        f"{base}/import?expected_revision=1&confirm_replace=true",
        headers={**lease, "Content-Type": DOCX_MEDIA_TYPE},
        content=source,
    )
    assert response.status_code == 201, response.text
    assert response.headers["cache-control"] == "no-store"
    result = response.json()
    imported = result["document"]
    record = result["import_record"]
    assert imported["revision"] == 2 and imported["schema_version"] == 2
    assert imported["last_version_number"] == 2
    assert imported["template_version_id"] == original["template_version_id"]
    assert result["version"]["content"] == imported["content"]
    assert record["source_sha256"] == sha256(source).hexdigest()
    assert record["source_size"] == len(source)
    assert record["version_id"] == result["version"]["id"]
    previous = (
        await api_client.get(f"/api/v1/document-versions/{record['previous_version_id']}")
    ).json()
    assert previous["content"] == original["content"]
    assert previous["schema_version"] == 1 and previous["document_revision"] == 1
    listing = await api_client.get(f"{base}/imports?limit=1&offset=0")
    assert listing.json()["items"] == [record]
    assert (await api_client.get(f"{base}/imports?offset=1")).json()["items"] == []
    download = await api_client.get(f"{base}/imports/{record['id']}/source")
    assert download.content == source and download.headers["x-content-type-options"] == "nosniff"
    asset_id = next(iter(LexicalContent.model_validate(imported["content"]).image_ids()))
    image_path = f"{base}/assets/{asset_id}"
    image = await api_client.get(image_path)
    assert image.status_code == 200 and image.headers["content-type"] == "image/png"
    assert image.content.startswith(b"\x89PNG")
    saved = await api_client.put(
        base,
        headers=lease,
        json={
            **save_payload(workspace, 2),
            "content": imported["content"],
            "schema_version": 2,
        },
    )
    assert saved.status_code == 200, saved.text
    restored = await api_client.post(
        f"{base}/restore",
        headers=lease,
        json={
            "expected_revision": 3,
            "version_id": previous["id"],
        },
    )
    assert restored.status_code == 200
    assert restored.json()["document"]["content"] == original["content"]
    assert (await api_client.get(image_path)).content == image.content
    assert (await api_client.get(f"{base}/imports/{record['id']}/source")).content == source
    authenticate(api_client, workspace.actors, workspace.actors.owner)
    assert (await api_client.get(image_path)).content == image.content
    assert (await api_client.get(f"{base}/imports")).json()["items"] == [record]
    assert (await api_client.get(f"{base}/imports/{record['id']}/source")).content == source


@pytest.mark.parametrize(
    "query",
    [
        "expected_revision=1",
        "expected_revision=1&confirm_replace=false",
        "expected_revision=0&confirm_replace=true",
        "expected_revision=1&confirm_replace=true&extra=1",
    ],
)
async def test_import_requires_confirmation_and_valid_parameters(
    api_client: AsyncClient,
    workspace: Workspace,
    query: str,
) -> None:
    lease = await acquire(api_client, workspace)
    response = await api_client.post(
        f"/api/v1/documents/{workspace.document_id}/import?{query}",
        headers={**lease, "Content-Type": DOCX_MEDIA_TYPE},
        content=docx(),
    )
    assert response.status_code == 422, response.text
    current = (await api_client.get(f"/api/v1/documents/{workspace.document_id}")).json()
    assert current["revision"] == 1 and current["last_version_number"] == 0


async def test_failed_imports_leave_no_records_or_versions(
    api_client: AsyncClient,
    workspace: Workspace,
    db_session: AsyncSession,
) -> None:
    base = f"/api/v1/documents/{workspace.document_id}"
    original = (await api_client.get(base)).json()
    lease = await acquire(api_client, workspace)
    for data, headers, expected in (
        (b"not a docx", {"Content-Type": DOCX_MEDIA_TYPE}, 422),
        (docx(), {"Content-Type": "text/html"}, 415),
        (docx(), {"Content-Type": DOCX_MEDIA_TYPE, "Content-Encoding": "gzip"}, 415),
        (
            docx(),
            {"Content-Type": DOCX_MEDIA_TYPE, "Content-Length": str(MAX_UPLOAD_BYTES + 1)},
            413,
        ),
        (b"x" * (MAX_UPLOAD_BYTES + 1), {"Content-Type": DOCX_MEDIA_TYPE}, 413),
        (docx(), {"Content-Type": DOCX_MEDIA_TYPE, "X-Edit-Lease": str(uuid4())}, 409),
        (docx(), {"Content-Type": DOCX_MEDIA_TYPE, "X-CSRF-Protection": ""}, 403),
    ):
        response = await api_client.post(
            f"{base}/import?expected_revision=1&confirm_replace=true",
            content=data,
            headers={**lease, **headers},
        )
        assert response.status_code == expected, response.text
        assert (await api_client.get(base)).json() == original
    assert await db_session.scalar(select(func.count()).select_from(DocumentImport)) == 0
    assert await db_session.scalar(select(func.count()).select_from(DocumentAsset)) == 0
    assert await db_session.scalar(select(func.count()).select_from(DocumentVersion)) == 0


async def test_chunked_upload_limit_is_enforced(
    api_client: AsyncClient,
    workspace: Workspace,
) -> None:
    async def chunks() -> AsyncIterator[bytes]:
        for _ in range(11):
            yield b"x" * (1024 * 1024)

    lease = await acquire(api_client, workspace)
    response = await api_client.post(
        f"/api/v1/documents/{workspace.document_id}/import?expected_revision=1&confirm_replace=true",
        headers={**lease, "Content-Type": DOCX_MEDIA_TYPE},
        content=chunks(),
    )
    assert response.status_code == 413


async def test_import_checks_owner_and_read_isolation(
    api_client: AsyncClient,
    workspace: Workspace,
) -> None:
    base = f"/api/v1/documents/{workspace.document_id}"
    lease = await acquire(api_client, workspace)
    response = await api_client.post(
        f"{base}/import?expected_revision=1&confirm_replace=true",
        headers={**lease, "Content-Type": DOCX_MEDIA_TYPE},
        content=image_docx(),
    )
    result = response.json()
    asset_id = next(iter(LexicalContent.model_validate(result["document"]["content"]).image_ids()))
    source_path = f"{base}/imports/{result['import_record']['id']}/source"
    for user in (workspace.actors.other, workspace.actors.peer, workspace.actors.outsider):
        authenticate(api_client, workspace.actors, user)
        for path in (f"{base}/imports", source_path, f"{base}/assets/{asset_id}"):
            assert (await api_client.get(path)).status_code == 404
        response = await api_client.post(
            f"{base}/import?expected_revision=2&confirm_replace=true",
            headers={**lease, "Content-Type": DOCX_MEDIA_TYPE},
            content=docx(),
        )
        assert response.status_code in (403, 404)
    authenticate(api_client, workspace.actors, workspace.actors.owner)
    assert (
        await api_client.post(
            f"{base}/import?expected_revision=2&confirm_replace=true",
            headers={**lease, "Content-Type": DOCX_MEDIA_TYPE},
            content=docx(),
        )
    ).status_code == 403
    api_client.cookies.clear()
    assert (await api_client.get(source_path)).status_code == 401


async def test_source_and_assets_cannot_be_updated_in_database(
    api_client: AsyncClient,
    workspace: Workspace,
    db_session: AsyncSession,
) -> None:
    lease = await acquire(api_client, workspace)
    response = await api_client.post(
        f"/api/v1/documents/{workspace.document_id}/import?expected_revision=1&confirm_replace=true",
        headers={**lease, "Content-Type": DOCX_MEDIA_TYPE},
        content=image_docx(),
    )
    record = response.json()["import_record"]
    for statement in (
        update(DocumentImport).where(DocumentImport.id == UUID(record["id"])).values(warnings={}),
        update(DocumentAsset)
        .where(DocumentAsset.document_id == UUID(workspace.document_id))
        .values(data=b"bad"),
    ):
        with pytest.raises(IntegrityError, match="immutable"):
            async with db_session.begin_nested():
                await db_session.execute(statement)


async def test_lease_expiry_and_stale_revision_reject_import(
    api_client: AsyncClient,
    workspace: Workspace,
    db_session: AsyncSession,
) -> None:
    lease = await acquire(api_client, workspace)
    base = f"/api/v1/documents/{workspace.document_id}"
    assert (
        await api_client.put(base, headers=lease, json=save_payload(workspace))
    ).status_code == 200
    response = await api_client.post(
        f"{base}/import?expected_revision=1&confirm_replace=true",
        headers={**lease, "Content-Type": DOCX_MEDIA_TYPE},
        content=docx(paragraph("Импорт")),
    )
    assert response.status_code == 409
    now = datetime.now(UTC)
    await db_session.execute(
        update(DocumentEditLease)
        .where(DocumentEditLease.document_id == UUID(workspace.document_id))
        .values(acquired_at=now - timedelta(minutes=5), expires_at=now - timedelta(minutes=1))
    )
    await db_session.commit()
    response = await api_client.post(
        f"{base}/import?expected_revision=2&confirm_replace=true",
        headers={**lease, "Content-Type": DOCX_MEDIA_TYPE},
        content=docx(),
    )
    assert response.status_code == 409
    assert (await api_client.get(f"{base}/imports")).json()["items"] == []


async def test_foreign_and_missing_image_references_are_rejected(
    api_client: AsyncClient,
    workspace: Workspace,
) -> None:
    base = f"/api/v1/documents/{workspace.document_id}"
    lease = await acquire(api_client, workspace)
    imported = await api_client.post(
        f"{base}/import?expected_revision=1&confirm_replace=true",
        headers={**lease, "Content-Type": DOCX_MEDIA_TYPE},
        content=image_docx(),
    )
    result = imported.json()
    original_content = result["document"]["content"]
    record_id = result["import_record"]["id"]
    asset_id = next(iter(LexicalContent.model_validate(original_content).image_ids()))
    invalid_content = LexicalContent.model_validate(original_content).stored()
    for node in content_nodes(invalid_content):
        if node.get("type") == "norma-image":
            node["asset_id"] = str(uuid4())
    rejected = await api_client.put(
        base,
        headers=lease,
        json={
            **save_payload(workspace, 2),
            "content": invalid_content,
            "schema_version": 2,
        },
    )
    assert rejected.status_code == 422
    assert (await api_client.get(base)).json() == result["document"]
    authenticate(api_client, workspace.actors, workspace.actors.owner)
    thesis = await api_client.post(
        "/api/v1/theses",
        json={
            "student_id": str(workspace.actors.peer.id),
            "title": "Другая ВКР",
            "start_date": "2026-01-01",
            "due_date": "2027-01-01",
        },
    )
    assert thesis.status_code == 201
    authenticate(api_client, workspace.actors, workspace.actors.peer)
    document = await api_client.post(
        f"/api/v1/theses/{thesis.json()['id']}/document",
        json={
            "template_version_id": workspace.template_version_id,
        },
    )
    assert document.status_code == 201
    other_base = f"/api/v1/documents/{document.json()['id']}"
    other_lease = await api_client.post(f"{other_base}/edit-lease")
    rejected = await api_client.put(
        other_base,
        headers={"X-Edit-Lease": other_lease.json()["lease_id"]},
        json={**save_payload(workspace), "content": original_content, "schema_version": 2},
    )
    assert rejected.status_code == 422
    assert (await api_client.get(f"{other_base}/assets/{asset_id}")).status_code == 404
    assert (await api_client.get(f"{other_base}/imports/{record_id}/source")).status_code == 404


async def test_real_docx_import_and_repeated_stale_request(
    api_client: AsyncClient,
    workspace: Workspace,
) -> None:
    source = (Path(__file__).parents[1] / "fixtures/synthetic-import.docx").read_bytes()
    lease = await acquire(api_client, workspace)
    base = f"/api/v1/documents/{workspace.document_id}"
    path = f"{base}/import?expected_revision=1&confirm_replace=true"
    response = await api_client.post(
        path, headers={**lease, "Content-Type": DOCX_MEDIA_TYPE}, content=source
    )
    assert response.status_code == 201, response.text
    imported = response.json()
    current = (await api_client.get(base)).json()
    assert current == imported["document"]
    assert any(n.get("type") == "table" for n in content_nodes(current["content"]))
    repeated = await api_client.post(
        path, headers={**lease, "Content-Type": DOCX_MEDIA_TYPE}, content=source
    )
    assert repeated.status_code == 409
    assert (await api_client.get(base)).json() == current
    assert len((await api_client.get(f"{base}/imports")).json()["items"]) == 1
