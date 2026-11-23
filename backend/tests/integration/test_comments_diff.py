from uuid import uuid4

import pytest
from httpx import AsyncClient

from tests.integration.actors import authenticate
from tests.integration.test_documents import Workspace, acquire, save_payload, snapshot
from tests.integration.test_documents import workspace as workspace

pytestmark = pytest.mark.integration


async def test_comments_utf16_validation_resolution_and_history(
    api_client: AsyncClient,
    workspace: Workspace,
) -> None:
    lease = await acquire(api_client, workspace)
    base = f"/api/v1/documents/{workspace.document_id}"
    assert (
        await api_client.put(base, headers=lease, json=save_payload(workspace, 1, "А😀 вывод"))
    ).status_code == 200
    version = await snapshot(api_client, workspace, lease, 2)
    path = f"/api/v1/document-versions/{version['id']}/comments"
    payload = {
        "body": "Уточнить вывод",
        "quote": "😀",
        "anchor": {"block_id": "0", "offset_start": 1, "offset_end": 3},
    }
    assert (await api_client.post(path, json=payload)).status_code == 403
    authenticate(api_client, workspace.actors, workspace.actors.owner)
    for bad in (
        {**payload, "quote": "чужой текст"},
        {**payload, "anchor": {"block_id": "0", "offset_start": 1, "offset_end": 2}},
        {**payload, "anchor": {"block_id": "8", "offset_start": 1, "offset_end": 3}},
        {**payload, "anchor": {"block_id": "0", "offset_start": 3, "offset_end": 1}},
        {**payload, "body": " \n "},
        {**payload, "body": "bad\x00text"},
        {**payload, "version_id": str(uuid4())},
    ):
        assert (await api_client.post(path, json=bad)).status_code == 422
    created = await api_client.post(path, json=payload)
    assert created.status_code == 201, created.text
    original = created.json()
    assert (
        original["anchor"] == payload["anchor"] and original["current_anchor"] == payload["anchor"]
    )
    assert not original["is_detached"] and original["author_id"] == str(workspace.actors.owner.id)
    detail = f"/api/v1/comments/{original['id']}"
    for user in (workspace.actors.peer, workspace.actors.other, workspace.actors.outsider):
        authenticate(api_client, workspace.actors, user)
        assert (await api_client.get(path)).status_code == 404
        assert (await api_client.get(detail)).status_code == 404
        assert (
            await api_client.patch(detail, json={"status": "resolved", "expected_revision": 1})
        ).status_code == 404
        assert (await api_client.get(f"{detail}/history")).status_code == 404
        assert (await api_client.post(path, json=payload)).status_code in (403, 404)
    authenticate(api_client, workspace.actors, workspace.actors.student)
    assert (await api_client.get(path)).json()["items"] == [original]
    assert (await api_client.get(detail)).headers["cache-control"] == "no-store"
    assert (
        await api_client.patch(detail, json={"status": "resolved", "expected_revision": 2})
    ).status_code == 409
    assert (
        await api_client.patch(
            detail, json={"status": "resolved", "expected_revision": 1, "quote": "Подмена"}
        )
    ).status_code == 422
    response = await api_client.patch(detail, json={"status": "resolved", "expected_revision": 1})
    assert response.status_code == 200
    resolved = response.json()
    assert resolved == {**original, "status": "resolved", "revision": 2}
    assert (await api_client.get(path)).json()["items"] == []
    assert (await api_client.get(f"{path}?include_resolved=true")).json()["items"] == [resolved]
    assert (
        await api_client.patch(detail, json={"status": "resolved", "expected_revision": 2})
    ).status_code == 409
    assert (
        await api_client.patch(detail, json={"status": "open", "expected_revision": 2})
    ).status_code == 422
    events = (await api_client.get(f"{detail}/history")).json()["items"]
    assert [(event["revision"], event["status"]) for event in events] == [
        (1, "open"),
        (2, "resolved"),
    ]
    assert events[1]["actor_id"] == str(workspace.actors.student.id)
    assert len((await api_client.get(f"{detail}/history?limit=1&offset=1")).json()["items"]) == 1
    # Marking a remark resolved has no effect on the thesis or stage state.
    assert (await api_client.get(f"/api/v1/theses/{workspace.thesis_id}")).json()[
        "completed_stages"
    ] == 0
    api_client.headers["X-CSRF-Protection"] = ""
    assert (
        await api_client.patch(detail, json={"status": "resolved", "expected_revision": 1})
    ).status_code == 403
    api_client.headers["X-CSRF-Protection"] = "1"
    api_client.cookies.clear()
    assert (await api_client.get(path)).status_code == 401


async def test_deleted_or_moved_quotes_keep_original_anchor_and_diff_text(
    api_client: AsyncClient,
    workspace: Workspace,
) -> None:
    lease = await acquire(api_client, workspace)
    base = f"/api/v1/documents/{workspace.document_id}"
    assert (
        await api_client.put(base, headers=lease, json=save_payload(workspace, 1, "Исходный вывод"))
    ).status_code == 200
    first = await snapshot(api_client, workspace, lease, 2)
    path = f"/api/v1/document-versions/{first['id']}/comments"
    authenticate(api_client, workspace.actors, workspace.actors.owner)
    response = await api_client.post(
        path,
        json={
            "body": "Уточнить",
            "quote": "вывод",
            "anchor": {"block_id": "0", "offset_start": 9, "offset_end": 14},
        },
    )
    assert response.status_code == 201, response.text
    original = response.json()
    detail = f"/api/v1/comments/{original['id']}"
    authenticate(api_client, workspace.actors, workspace.actors.student)
    assert (
        await api_client.put(base, headers=lease, json=save_payload(workspace, 2, "Новый вывод"))
    ).status_code == 200
    moved = (await api_client.get(detail)).json()
    assert moved["current_anchor"]["offset_start"] == 6
    assert moved["anchor"] == original["anchor"] and moved["quote"] == "вывод"
    assert (
        await api_client.put(base, headers=lease, json=save_payload(workspace, 3, "Другой текст"))
    ).status_code == 200
    second = await snapshot(api_client, workspace, lease, 4)
    detached = (await api_client.get(detail)).json()
    assert detached["is_detached"] and detached["current_anchor"] is None
    assert detached["anchor"] == original["anchor"] and detached["quote"] == "вывод"
    assert (await api_client.get(path)).json()["items"] == []
    assert (await api_client.get(f"{path}?include_detached=true")).json()["items"] == [detached]
    diff = await api_client.get(
        f"{base}/diff", params={"base": str(first["id"]), "target": str(second["id"])}
    )
    assert diff.status_code == 200, diff.text
    assert diff.headers["cache-control"] == "no-store"
    changes = diff.json()["changes"]
    assert changes[0]["kind"] == "changed"
    assert changes[0]["before"]["text"] == "Исходный вывод"
    assert changes[0]["after"]["text"] == "Другой текст"
    assert "".join(item["before"] for item in changes[0]["text_changes"]) == "Исходный вывод"
    assert (await api_client.get(f"/api/v1/document-versions/{first['id']}")).json() == first
    same = await api_client.get(
        f"{base}/diff", params={"base": str(first["id"]), "target": str(first["id"])}
    )
    assert [item["kind"] for item in same.json()["changes"]] == ["equal"]
    authenticate(api_client, workspace.actors, workspace.actors.owner)
    assert (
        await api_client.get(
            f"{base}/diff", params={"base": str(first["id"]), "target": str(second["id"])}
        )
    ).status_code == 200
    for user in (workspace.actors.other, workspace.actors.peer):
        authenticate(api_client, workspace.actors, user)
        assert (
            await api_client.get(
                f"{base}/diff", params={"base": str(first["id"]), "target": str(second["id"])}
            )
        ).status_code == 404
    authenticate(api_client, workspace.actors, workspace.actors.student)
    assert (
        await api_client.get(
            f"{base}/diff", params={"base": str(first["id"]), "target": str(uuid4())}
        )
    ).status_code == 404


async def test_diff_rejects_version_from_another_document_of_same_supervisor(
    api_client: AsyncClient,
    workspace: Workspace,
) -> None:
    lease = await acquire(api_client, workspace)
    own = await snapshot(api_client, workspace, lease, 1)
    authenticate(api_client, workspace.actors, workspace.actors.owner)
    thesis = await api_client.post(
        "/api/v1/theses",
        json={
            "student_id": str(workspace.actors.peer.id),
            "title": "Другая работа",
            "start_date": "2026-01-01",
            "due_date": "2027-06-30",
        },
    )
    assert thesis.status_code == 201
    authenticate(api_client, workspace.actors, workspace.actors.peer)
    document = await api_client.post(
        f"/api/v1/theses/{thesis.json()['id']}/document",
        json={"template_version_id": workspace.template_version_id},
    )
    assert document.status_code == 201
    doc_path = f"/api/v1/documents/{document.json()['id']}"
    other_lease = await api_client.post(f"{doc_path}/edit-lease")
    version = await api_client.post(
        f"{doc_path}/versions",
        headers={"X-Edit-Lease": other_lease.json()["lease_id"]},
        json={"expected_revision": 1},
    )
    assert version.status_code == 201
    authenticate(api_client, workspace.actors, workspace.actors.owner)
    response = await api_client.get(
        f"/api/v1/documents/{workspace.document_id}/diff",
        params={"base": str(own["id"]), "target": version.json()["id"]},
    )
    assert response.status_code == 404
