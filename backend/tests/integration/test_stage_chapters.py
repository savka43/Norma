from copy import deepcopy
from typing import cast
from uuid import uuid4

import pytest
from httpx import AsyncClient
from pydantic import JsonValue

from app.api_v1.documents.docx_import import DOCX_MEDIA_TYPE
from tests.document_helpers import parameters, text_block, with_blocks
from tests.docx_helpers import docx, paragraph
from tests.integration.actors import authenticate
from tests.integration.test_documents import Workspace, acquire, save_payload, snapshot
from tests.integration.test_documents import workspace as workspace
from tests.integration.test_stage_review import decision, stage_plan, submit

pytestmark = pytest.mark.integration


async def test_chapter_review_preserves_snapshot_while_other_text_can_change(
    api_client: AsyncClient, workspace: Workspace
) -> None:
    first, second, unbound = await stage_plan(api_client, workspace, 3)
    lease = await acquire(api_client, workspace)
    base = f"/api/v1/documents/{workspace.document_id}"
    heading = text_block("Глава 1", tag="h1", stage_id=first)
    protected = text_block("Проверяемый текст")
    next_heading = text_block("Глава 2", tag="h1", stage_id=second)
    blocks = [heading, protected, next_heading, text_block("Черновик")]
    original = with_blocks(*blocks)

    async def save(data: dict[str, JsonValue], rev: int, **changes: object) -> int:
        response = await api_client.put(
            base,
            headers=lease,
            json={**save_payload(workspace, rev), "content": data, "schema_version": 4, **changes},
        )
        return response.status_code

    old_version = await snapshot(api_client, workspace, lease, 1)
    assert await save(original, 1) == 200
    action = await submit(api_client, first, lease, 4, 2)
    stage = cast(dict[str, JsonValue], action["stage"])
    version_id = stage["submitted_version_id"]
    version_path = f"/api/v1/document-versions/{version_id}"
    authenticate(api_client, workspace.actors, workspace.actors.owner)
    pinned = (await api_client.get(version_path)).json()
    assert pinned["content"] == original
    exported = await api_client.post(f"{version_path}/exports", json={"format": "docx"})
    assert exported.status_code == 200, exported.text
    history = (await api_client.get(f"/api/v1/stages/{first}/submissions")).json()["items"]
    assert history[0]["scope"] == "chapter"
    updated_template = await api_client.post(
        f"/api/v1/formatting-templates/{workspace.template_id}/versions",
        json={"expected_version": 1, "parameters": parameters(18)},
    )
    assert updated_template.status_code == 201
    authenticate(api_client, workspace.actors, workspace.actors.student)

    draft = with_blocks(text_block("Введение"), *blocks[:3], text_block("Глава 2 исправлена"))
    assert await save(draft, 2) == 200
    assert await save(draft, 2) == 409
    assert await save(draft, 3, template_version_id=updated_template.json()["id"]) == 409
    root_change = deepcopy(draft)
    cast(dict[str, JsonValue], root_change["root"])["direction"] = "rtl"
    for rejected in (
        root_change,
        with_blocks(text_block("Без привязки", tag="h1"), *blocks[1:]),
        with_blocks(heading, text_block("Подмена"), *blocks[2:]),
        with_blocks(heading, text_block("Новая граница", tag="h1"), *blocks[1:]),
        with_blocks(heading, protected, text_block("Глава 2", tag="h2"), blocks[-1]),
    ):
        assert await save(rejected, 3) == 409
    assert (await api_client.get(base)).json()["content"] == draft
    assert (await api_client.get(version_path)).json() == pinned

    restore = f"{base}/restore"
    assert (
        await api_client.post(
            restore, headers=lease, json={"version_id": old_version["id"], "expected_revision": 3}
        )
    ).status_code == 409
    assert (
        await api_client.post(
            f"{base}/import",
            headers={**lease, "Content-Type": DOCX_MEDIA_TYPE},
            params={"expected_revision": 3, "confirm_replace": "true"},
            content=docx(paragraph("Замена")),
        )
    ).status_code == 409
    restored = await api_client.post(
        restore, headers=lease, json={"version_id": version_id, "expected_revision": 3}
    )
    assert restored.status_code == 200, restored.text
    assert restored.json()["document"]["content"] == original

    await submit(api_client, second, lease, 5, 4)
    assert await save(draft, 4) == 409  # Chapter 2 is now protected as well.
    assert await save(with_blocks(*blocks[2:], *blocks[:2]), 4) == 409
    assert await save(with_blocks(text_block("Введение"), *blocks), 4) == 200
    full_review = await submit(api_client, unbound, lease, 6, 5)
    history = (await api_client.get(f"/api/v1/stages/{unbound}/submissions")).json()["items"]
    assert history[0]["scope"] == "document"
    assert await save(with_blocks(text_block("Новое введение"), *blocks), 5) == 409
    authenticate(api_client, workspace.actors, workspace.actors.owner)
    for offset, (stage_id, review) in enumerate(((unbound, full_review), (first, action))):
        reviewed = cast(dict[str, JsonValue], review["stage"])
        response = await api_client.post(
            f"/api/v1/stages/{stage_id}/request-changes",
            json=decision(7 + offset, reviewed["submitted_version_id"]),
        )
        assert response.status_code == 200, response.text
    authenticate(api_client, workspace.actors, workspace.actors.student)
    assert (
        await save(with_blocks(heading, text_block("Исправленное замечание"), *blocks[2:]), 5)
        == 200
    )
    assert (await api_client.get(version_path)).json() == pinned


async def test_chapter_binding_validates_document_structure_and_thesis_ownership(
    api_client: AsyncClient, workspace: Workspace
) -> None:
    stage = (await stage_plan(api_client, workspace))[0]
    authenticate(api_client, workspace.actors, workspace.actors.owner)
    other_thesis = await api_client.post(
        "/api/v1/theses",
        json={
            "student_id": str(workspace.actors.peer.id),
            "title": "Другая ВКР",
            "start_date": "2026-01-01",
            "due_date": "2027-06-30",
        },
    )
    assert other_thesis.status_code == 201
    other_stage = await api_client.post(
        f"/api/v1/theses/{other_thesis.json()['id']}/stages",
        json={
            "name": "Чужая глава",
            "position": 1,
            "due_date": "2027-05-01",
            "expected_revision": 1,
        },
    )
    assert other_stage.status_code == 201
    foreign_id = other_stage.json()["items"][0]["id"]
    authenticate(api_client, workspace.actors, workspace.actors.student)
    lease = await acquire(api_client, workspace)
    base = f"/api/v1/documents/{workspace.document_id}"
    before = (await api_client.get(base)).json()
    heading = text_block("Глава", tag="h1", stage_id=stage)
    for schema_version, data in (
        (3, with_blocks(heading)),
        (4, with_blocks(heading, heading)),
        (4, with_blocks(text_block("Подраздел", tag="h2", stage_id=stage))),
        (4, with_blocks(text_block("Подмена", tag="h1", stage_id="invalid"))),
        (4, with_blocks(text_block("Подмена", tag="h1", stage_id=str(uuid4())))),
        (4, with_blocks(text_block("Подмена", tag="h1", stage_id=foreign_id))),
    ):
        result = await api_client.put(
            base,
            headers=lease,
            json={**save_payload(workspace), "content": data, "schema_version": schema_version},
        )
        assert result.status_code == 422, result.text
    assert (await api_client.get(base)).json() == before


@pytest.mark.parametrize("inside_review", [False, True])
async def test_apply_formatting_compares_protected_blocks_before_writing(
    api_client: AsyncClient, workspace: Workspace, inside_review: bool
) -> None:
    stage = (await stage_plan(api_client, workspace))[0]
    lease = await acquire(api_client, workspace)
    base = f"/api/v1/documents/{workspace.document_id}"
    heading = text_block("Глава", tag="h1", stage_id=stage)
    body = cast(dict[str, JsonValue], text_block("Абзац с ручным отступом"))
    body["indent"] = 3
    blocks = [heading, body] if inside_review else [body, heading]
    saved = await api_client.put(
        base,
        headers=lease,
        json={**save_payload(workspace), "schema_version": 4, "content": with_blocks(*blocks)},
    )
    assert saved.status_code == 200, saved.text
    submitted = await submit(api_client, stage, lease, 2, 2)
    version_id = cast(dict[str, JsonValue], submitted["stage"])["submitted_version_id"]
    version_path = f"/api/v1/document-versions/{version_id}"
    pinned = (await api_client.get(version_path)).json()
    before = (await api_client.get(base)).json()
    formatted = await api_client.post(
        f"{base}/apply-formatting",
        headers=lease,
        json={
            "expected_revision": 2,
            "template_version_id": workspace.template_version_id,
            "confirm_apply": True,
        },
    )
    if inside_review:
        assert formatted.status_code == 409, formatted.text
        assert (await api_client.get(base)).json() == before
    else:
        assert formatted.status_code == 200, formatted.text
        assert formatted.json()["document"]["content"]["root"]["children"][0]["indent"] == 0
    assert (await api_client.get(version_path)).json() == pinned
