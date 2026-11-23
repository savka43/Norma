from io import BytesIO
from uuid import uuid4

import pytest
from docx import Document
from httpx import AsyncClient
from PIL import Image, PngImagePlugin
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api_v1.documents.docx_import import MAX_UPLOAD_BYTES
from app.core.models import DocumentAsset
from tests.document_helpers import text_block
from tests.integration.actors import authenticate
from tests.integration.test_documents import Workspace, acquire, save_payload, snapshot
from tests.integration.test_documents import workspace as workspace
from tests.integration.test_stage_review import stage_plan, submit

pytestmark = pytest.mark.integration


def image_bytes(image_format: str = "PNG") -> bytes:
    output = BytesIO()
    with Image.new("RGBA" if image_format == "PNG" else "RGB", (3, 2), "red") as image:
        if image_format == "PNG":
            info = PngImagePlugin.PngInfo()
            info.add_text("Comment", "Metadata must not be retained")
            image.save(output, format=image_format, pnginfo=info)
        else:
            image.save(output, format=image_format)
    return output.getvalue()


@pytest.mark.parametrize(
    ("media_type", "image_format"), [("image/png", "PNG"), ("image/jpeg", "JPEG")]
)
async def test_upload_insert_and_export_image(
    api_client: AsyncClient, workspace: Workspace, media_type: str, image_format: str
) -> None:
    stage = (await stage_plan(api_client, workspace))[0]
    lease = await acquire(api_client, workspace)
    base = f"/api/v1/documents/{workspace.document_id}"
    content = (await api_client.get(base)).json()["content"]
    blocks = content["root"]["children"]
    blocks[:] = [
        text_block("На проверке", tag="h1", stage_id=stage),
        text_block("Другая глава", tag="h1"),
    ]
    payload = {**save_payload(workspace), "content": content, "schema_version": 4}
    saved = await api_client.put(base, json=payload, headers=lease)
    assert saved.status_code == 200, saved.text
    await submit(api_client, stage, lease, 2, 2)
    before = (await api_client.get(base)).json()
    uploaded = await api_client.post(
        f"{base}/assets?expected_revision=2",
        headers={**lease, "Content-Type": media_type},
        content=image_bytes(image_format),
    )
    assert uploaded.status_code == 201, uploaded.text
    asset = uploaded.json()
    assert (asset["width"], asset["height"], asset["media_type"]) == (3, 2, "image/png")
    assert (await api_client.get(base)).json() == before
    assert (await api_client.get(f"{base}/imports")).json()["items"] == []
    asset_path = f"{base}/assets/{asset['id']}"
    stored = await api_client.get(asset_path)
    assert stored.status_code == 200 and stored.headers["content-type"] == "image/png"
    with Image.open(BytesIO(stored.content)) as image:
        assert image.format == "PNG" and image.size == (3, 2) and not image.info

    paragraph = {**blocks[1], "type": "paragraph"}
    del paragraph["tag"]
    paragraph["children"] = [
        {"type": "norma-image", "version": 1, "asset_id": asset["id"], "alt_text": "Рисунок"}
    ]
    blocks.append(paragraph)
    inserted = await api_client.put(base, json={**payload, "expected_revision": 2}, headers=lease)
    assert inserted.status_code == 200, inserted.text
    version = await snapshot(api_client, workspace, lease, 3)
    authenticate(api_client, workspace.actors, workspace.actors.owner)
    exported = await api_client.post(
        f"/api/v1/document-versions/{version['id']}/exports", json={"format": "docx"}
    )
    assert exported.status_code == 200, exported.text
    assert len(Document(BytesIO(exported.content)).inline_shapes) == 1
    assert (await api_client.get(asset_path)).content == stored.content
    authenticate(api_client, workspace.actors, workspace.actors.outsider)
    assert (await api_client.get(asset_path)).status_code == 404


async def test_upload_rejections_leave_document_and_assets_unchanged(
    api_client: AsyncClient, workspace: Workspace, db_session: AsyncSession
) -> None:
    base = f"/api/v1/documents/{workspace.document_id}"
    original = (await api_client.get(base)).json()
    lease = await acquire(api_client, workspace)
    source = image_bytes()
    for revision, data, headers, expected in (
        (1, source, {"Content-Type": "image/svg+xml"}, 415),
        (1, source, {"Content-Type": "image/jpeg"}, 422),
        (1, b"not an image", {}, 422),
        (1, source, {"Content-Length": str(MAX_UPLOAD_BYTES + 1)}, 413),
        (1, source, {"X-Edit-Lease": str(uuid4())}, 409),
        (2, source, {}, 409),
        (1, source, {"X-CSRF-Protection": ""}, 403),
    ):
        rejected = await api_client.post(
            f"{base}/assets?expected_revision={revision}",
            headers={"Content-Type": "image/png", **lease, **headers},
            content=data,
        )
        assert rejected.status_code == expected, rejected.text
    for user, expected in ((workspace.actors.owner, 403), (workspace.actors.outsider, 404)):
        authenticate(api_client, workspace.actors, user)
        rejected = await api_client.post(
            f"{base}/assets?expected_revision=1",
            headers={"Content-Type": "image/png", **lease},
            content=source,
        )
        assert rejected.status_code == expected, rejected.text
    authenticate(api_client, workspace.actors, workspace.actors.student)
    assert (await api_client.get(base)).json() == original
    assert await db_session.scalar(select(func.count()).select_from(DocumentAsset)) == 0
