import shutil
from datetime import UTC, datetime, timedelta
from io import BytesIO
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from docx import Document
from httpx import AsyncClient
from pypdf import PdfReader
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api_v1.documents.export.docx import DOCX_MEDIA_TYPE
from app.core.config import Settings
from app.core.models import DocumentEditLease
from tests.document_helpers import parameters, text_block
from tests.formatting_helpers import formatting_content
from tests.integration.actors import authenticate
from tests.integration.test_documents import Workspace, acquire, save_payload, snapshot
from tests.integration.test_documents import workspace as workspace
from tests.integration.test_stage_review import stage_plan, submit

pytestmark = pytest.mark.integration


async def test_gost_preset_is_editable_and_requires_login(
    api_client: AsyncClient, workspace: Workspace
) -> None:
    response = await api_client.get("/api/v1/formatting-presets/gost-7-32-2017")
    assert response.status_code == 200
    preset = response.json()
    assert preset["body"]["font_family"] == "Times New Roman"
    assert preset["margins"]["left_mm"] == 30
    authenticate(api_client, workspace.actors, workspace.actors.owner)
    preset["body"]["font_size_pt"] = 18
    saved = await api_client.post(
        "/api/v1/formatting-templates",
        json={"name": "Изменённая предустановка", "parameters": preset},
    )
    assert saved.status_code == 201
    assert saved.json()["version"]["parameters"]["body"]["font_size_pt"] == 18
    api_client.cookies.clear()
    assert (await api_client.get("/api/v1/formatting-presets/gost-7-32-2017")).status_code == 401


async def test_check_apply_export_restore_keep_pinned_template_and_old_versions(
    api_client: AsyncClient, workspace: Workspace
) -> None:
    base = f"/api/v1/documents/{workspace.document_id}"
    lease = await acquire(api_client, workspace)
    payload = {**save_payload(workspace), "content": formatting_content(), "schema_version": 3}
    saved = await api_client.put(base, headers=lease, json=payload)
    assert saved.status_code == 200, saved.text
    first = await snapshot(api_client, workspace, lease, 2)
    version_path = f"/api/v1/document-versions/{first['id']}"
    report = await api_client.post(f"{version_path}/format-check")
    assert report.status_code == 200
    assert report.json()["issue_count"] == 2 and not report.json()["conforms"]
    authenticate(api_client, workspace.actors, workspace.actors.owner)
    latest = await api_client.post(
        f"/api/v1/formatting-templates/{workspace.template_id}/versions",
        json={"expected_version": 1, "parameters": parameters(18)},
    )
    assert latest.status_code == 201
    # Supervisor can inspect/check/export the submitted version but cannot edit the document.
    old = await api_client.post(f"{version_path}/exports", json={"format": "docx"})
    assert old.status_code == 200, old.text
    assert old.headers["content-type"] == DOCX_MEDIA_TYPE
    assert old.headers["x-template-version"] == workspace.template_version_id
    assert old.headers["x-export-warnings"] == "manual_formatting_normalized"
    assert old.headers["cache-control"] == "no-store"
    assert old.headers["x-content-type-options"] == "nosniff"
    assert old.headers["content-disposition"].startswith("attachment;")
    old_doc = Document(BytesIO(old.content))
    assert old_doc.paragraphs[1].style is not None
    assert old_doc.paragraphs[1].style.font.size is not None
    assert old_doc.paragraphs[1].style.font.size.pt == 14
    authenticate(api_client, workspace.actors, workspace.actors.student)
    apply = {
        "expected_revision": 2,
        "template_version_id": latest.json()["id"],
        "confirm_apply": True,
    }
    response = await api_client.post(f"{base}/apply-formatting", headers=lease, json=apply)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["document"]["revision"] == 3 and result["corrected_issues"] == 2
    assert result["previous_version"]["content"] == first["content"]
    assert result["previous_version"]["template_version_id"] == workspace.template_version_id
    assert result["version"]["template_version_id"] == latest.json()["id"]
    assert result["version"]["number"] == 3
    after = f"/api/v1/document-versions/{result['version']['id']}"
    assert (await api_client.post(f"{after}/format-check")).json()["conforms"]
    new_export = await api_client.post(f"{after}/exports", json={"format": "docx"})
    new_doc = Document(BytesIO(new_export.content))
    assert new_doc.paragraphs[1].style is not None
    assert new_doc.paragraphs[1].style.font.size is not None
    assert new_doc.paragraphs[1].style.font.size.pt == 18
    assert (await api_client.get(version_path)).json() == first
    assert (await api_client.post(f"{version_path}/format-check")).json() == report.json()
    assert (await api_client.get(base)).json() == result["document"]
    assert (
        await api_client.post(f"{base}/apply-formatting", headers=lease, json=apply)
    ).status_code == 409
    assert (await api_client.get(base)).json() == result["document"]
    restored = await api_client.post(
        f"{base}/restore", headers=lease, json={"expected_revision": 3, "version_id": first["id"]}
    )
    assert restored.status_code == 200
    assert restored.json()["document"]["content"] == first["content"]


async def test_formatting_rights_csrf_and_foreign_version_isolation(
    api_client: AsyncClient, workspace: Workspace
) -> None:
    base = f"/api/v1/documents/{workspace.document_id}"
    lease = await acquire(api_client, workspace)
    version = await snapshot(api_client, workspace, lease, 1)
    path = f"/api/v1/document-versions/{version['id']}"
    apply = {
        "expected_revision": 1,
        "template_version_id": workspace.template_version_id,
        "confirm_apply": True,
    }
    for user in (workspace.actors.other, workspace.actors.peer, workspace.actors.outsider):
        authenticate(api_client, workspace.actors, user)
        assert (await api_client.post(f"{path}/format-check")).status_code == 404
        assert (
            await api_client.post(f"{path}/exports", json={"format": "docx"})
        ).status_code == 404
        assert (
            await api_client.post(f"{base}/apply-formatting", headers=lease, json=apply)
        ).status_code in (403, 404)
    authenticate(api_client, workspace.actors, workspace.actors.owner)
    assert (
        await api_client.post(f"{base}/apply-formatting", headers=lease, json=apply)
    ).status_code == 403
    authenticate(api_client, workspace.actors, workspace.actors.student)
    api_client.headers["X-CSRF-Protection"] = ""
    for suffix in ("format-check", "exports"):
        assert (
            await api_client.post(f"{path}/{suffix}", json={"format": "docx"})
        ).status_code == 403
    assert (
        await api_client.post(f"{base}/apply-formatting", headers=lease, json=apply)
    ).status_code == 403
    api_client.headers["X-CSRF-Protection"] = "1"
    api_client.cookies.clear()
    assert (await api_client.post(f"{path}/exports", json={"format": "docx"})).status_code == 401


async def test_formatting_invalid_inputs_expired_lease_and_failed_export_do_not_mutate(
    api_client: AsyncClient, workspace: Workspace, db_session: AsyncSession
) -> None:
    base = f"/api/v1/documents/{workspace.document_id}"
    lease = await acquire(api_client, workspace)
    before = (await api_client.get(base)).json()
    apply = {
        "expected_revision": 1,
        "template_version_id": workspace.template_version_id,
        "confirm_apply": True,
    }
    for patch, expected in (
        ({"confirm_apply": False}, 422),
        ({"confirm_apply": 1}, 422),
        ({"expected_revision": 2}, 409),
        ({"template_version_id": str(uuid4())}, 404),
        ({"extra": 1}, 422),
    ):
        response = await api_client.post(
            f"{base}/apply-formatting", headers=lease, json={**apply, **patch}
        )
        assert response.status_code == expected, response.text
        assert (await api_client.get(base)).json() == before
    version = await snapshot(api_client, workspace, lease, 1)
    path = f"/api/v1/document-versions/{version['id']}"
    for body in ({"format": "html"}, {"format": "docx", "template_version_id": str(uuid4())}):
        assert (await api_client.post(f"{path}/exports", json=body)).status_code == 422
    assert (
        await api_client.post(
            f"/api/v1/document-versions/{uuid4()}/exports", json={"format": "docx"}
        )
    ).status_code == 404
    now = datetime.now(UTC)
    await db_session.execute(
        update(DocumentEditLease)
        .where(DocumentEditLease.document_id == UUID(workspace.document_id))
        .values(acquired_at=now - timedelta(minutes=5), expires_at=now - timedelta(minutes=1))
    )
    await db_session.commit()
    assert (
        await api_client.post(f"{base}/apply-formatting", headers=lease, json=apply)
    ).status_code == 409
    assert (await api_client.get(base)).json()["revision"] == 1


async def test_imported_docx_round_trip_preserves_text_table_image_and_history(
    api_client: AsyncClient, workspace: Workspace
) -> None:
    base = f"/api/v1/documents/{workspace.document_id}"
    lease = await acquire(api_client, workspace)
    source = (Path(__file__).parents[1] / "fixtures/synthetic-import.docx").read_bytes()
    imported = await api_client.post(
        f"{base}/import?expected_revision=1&confirm_replace=true",
        headers={**lease, "Content-Type": DOCX_MEDIA_TYPE},
        content=source,
    )
    assert imported.status_code == 201
    result = imported.json()
    path = f"/api/v1/document-versions/{result['version']['id']}/exports"
    exported = await api_client.post(path, json={"format": "docx"})
    assert exported.status_code == 200, exported.text
    doc = Document(BytesIO(exported.content))
    assert doc.paragraphs[0].text == "Синтетическая ВКР"
    assert len(doc.tables) == 1 and doc.tables[0].cell(1, 1).text == "Ячейка 4"
    assert len(doc.inline_shapes) == 1
    reimported = await api_client.post(
        f"{base}/import?expected_revision=2&confirm_replace=true",
        headers={**lease, "Content-Type": DOCX_MEDIA_TYPE},
        content=exported.content,
    )
    assert reimported.status_code == 201, reimported.text
    round_trip = reimported.json()["version"]
    assert round_trip["id"] != result["version"]["id"]
    round_trip_export = await api_client.post(
        f"/api/v1/document-versions/{round_trip['id']}/exports", json={"format": "docx"}
    )
    assert round_trip_export.status_code == 200, round_trip_export.text
    round_trip_doc = Document(BytesIO(round_trip_export.content))
    assert [p.text for p in round_trip_doc.paragraphs] == [p.text for p in doc.paragraphs]
    assert len(round_trip_doc.tables) == 1
    assert round_trip_doc.tables[0].cell(1, 1).text == "Ячейка 4"
    assert len(round_trip_doc.inline_shapes) == 1
    restored = await api_client.post(
        f"{base}/restore",
        headers=lease,
        json={
            "expected_revision": 3,
            "version_id": result["import_record"]["previous_version_id"],
        },
    )
    assert restored.status_code == 200
    assert (await api_client.get(path.removesuffix("/exports"))).json() == result["version"]
    repeated = await api_client.post(path, json={"format": "docx"})
    assert (
        repeated.status_code == 200 and len(Document(BytesIO(repeated.content)).inline_shapes) == 1
    )


async def test_pdf_http_errors_leave_document_and_version_unchanged(
    api_client: AsyncClient,
    workspace: Workspace,
    integration_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lease = await acquire(api_client, workspace)
    version = await snapshot(api_client, workspace, lease, 1)
    base = f"/api/v1/documents/{workspace.document_id}"
    before = (await api_client.get(base)).json()
    path = f"/api/v1/document-versions/{version['id']}"
    monkeypatch.setattr(integration_settings, "pdf_converter", "norma-nonexistent-converter")
    response = await api_client.post(f"{path}/exports", json={"format": "pdf"})
    assert response.status_code == 503
    assert (await api_client.get(base)).json() == before
    assert (await api_client.get(path)).json() == version


async def test_real_pdf_export_of_submitted_chapter_uses_pinned_multipage_document(
    api_client: AsyncClient,
    workspace: Workspace,
    integration_settings: Settings,
) -> None:
    if not shutil.which(integration_settings.pdf_converter):
        pytest.skip("Run real PDF HTTP test inside the API image with LibreOffice")
    stage = (await stage_plan(api_client, workspace))[0]
    lease = await acquire(api_client, workspace)
    base = f"/api/v1/documents/{workspace.document_id}"
    source = (Path(__file__).parents[1] / "fixtures/synthetic-import.docx").read_bytes()
    imported = await api_client.post(
        f"{base}/import?expected_revision=1&confirm_replace=true",
        headers={**lease, "Content-Type": DOCX_MEDIA_TYPE},
        content=source,
    )
    assert imported.status_code == 201
    content = imported.json()["document"]["content"]
    blocks = content["root"]["children"]
    assert blocks[0]["tag"] == "h1"
    blocks[0]["$"] = {"normaStageId": stage}
    blocks.extend(
        [
            text_block("Следующая глава", tag="h1"),
            *(text_block(f"Абзац {index} для многостраничной проверки.") for index in range(90)),
            text_block("Последний сохранённый абзац"),
        ]
    )
    payload = {**save_payload(workspace, 2), "content": content, "schema_version": 4}
    saved = await api_client.put(base, headers=lease, json=payload)
    assert saved.status_code == 200, saved.text
    await submit(api_client, stage, lease, 2, 3)
    submission = (await api_client.get(f"/api/v1/stages/{stage}/submissions")).json()["items"][0]
    assert submission["scope"] == "chapter"
    blocks[-1] = text_block("Последний изменённый абзац")
    edited = await api_client.put(base, headers=lease, json={**payload, "expected_revision": 3})
    assert edited.status_code == 200, edited.text

    version_id = submission["version_id"]
    authenticate(api_client, workspace.actors, workspace.actors.owner)
    response = await api_client.post(
        f"/api/v1/document-versions/{version_id}/exports", json={"format": "pdf"}
    )
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["x-document-version"] == version_id
    assert response.headers["x-template-version"] == workspace.template_version_id
    assert "font_substitution" in response.headers["x-export-warnings"]
    reader = PdfReader(BytesIO(response.content))
    assert len(reader.pages) >= 2
    extracted = "\n".join(page.extract_text() for page in reader.pages)
    assert "Синтетическая ВКР" in extracted
    assert "Ячейка 4" in extracted and "Конец документа" in extracted
    assert "Последний сохранённый абзац" in extracted
    assert "Последний изменённый абзац" not in extracted
    images = {
        image.indirect_reference.idnum
        for page in reader.pages
        for image in page.images
        if image.indirect_reference is not None
    }
    assert len(reader.pages[0].images) == 1 and len(images) == 1
