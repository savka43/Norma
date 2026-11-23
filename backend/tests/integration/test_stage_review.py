from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from pydantic import JsonValue
from sqlalchemy import select, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api_v1.documents.docx_import import DOCX_MEDIA_TYPE
from app.core.models import Comment, CommentEvent, DocumentEditLease, StageEvent, StageSubmission
from tests.docx_helpers import docx, paragraph
from tests.integration.actors import authenticate
from tests.integration.test_documents import Workspace, acquire, save_payload, snapshot
from tests.integration.test_documents import workspace as workspace

pytestmark = pytest.mark.integration


async def stage_plan(client: AsyncClient, ws: Workspace, count: int = 1) -> list[str]:
    authenticate(client, ws.actors, ws.actors.owner)
    ids: list[str] = []
    for index in range(count):
        response = await client.post(
            f"/api/v1/theses/{ws.thesis_id}/stages",
            json={
                "name": f"Глава {index + 1}",
                "position": index + 1,
                "due_date": "2027-05-01",
                "expected_revision": index + 1,
            },
        )
        assert response.status_code == 201, response.text
        ids.append(response.json()["items"][-1]["id"])
    authenticate(client, ws.actors, ws.actors.student)
    return ids


async def submit(
    client: AsyncClient,
    stage_id: str,
    lease: dict[str, str],
    revision: int,
    document_revision: int = 1,
) -> dict[str, JsonValue]:
    response = await client.post(
        f"/api/v1/stages/{stage_id}/submit",
        headers=lease,
        json={"expected_revision": revision, "expected_document_revision": document_revision},
    )
    assert response.status_code == 201, response.text
    return cast(dict[str, JsonValue], response.json())


def decision(revision: int, version_id: object) -> dict[str, object]:
    return {"expected_revision": revision, "submitted_version_id": version_id}


async def test_full_review_cycle_pins_snapshots_and_keeps_submission_history(
    api_client: AsyncClient,
    workspace: Workspace,
) -> None:
    stages = await stage_plan(api_client, workspace, 2)
    lease = await acquire(api_client, workspace)
    base = f"/api/v1/documents/{workspace.document_id}"
    saved = await api_client.put(base, headers=lease, json=save_payload(workspace))
    assert saved.status_code == 200
    first = await submit(api_client, stages[0], lease, 3, 2)
    assert first["revision"] == 4
    stage = first["stage"]
    assert isinstance(stage, dict)
    version_id = stage["submitted_version_id"]
    version_path = f"/api/v1/document-versions/{version_id}"
    original = (await api_client.get(version_path)).json()
    assert original["document_revision"] == 2 and original["number"] == 1
    authenticate(api_client, workspace.actors, workspace.actors.owner)
    assert (await api_client.get(version_path)).json() == original
    assert (await api_client.get(f"/api/v1/theses/{workspace.thesis_id}")).json()[
        "progress_percent"
    ] == 0
    returned = await api_client.post(
        f"/api/v1/stages/{stages[0]}/request-changes",
        json={**decision(4, version_id), "comment": "Уточнить выводы"},
    )
    assert returned.status_code == 200, returned.text
    assert returned.json()["stage"]["status"] == "changes_requested"
    authenticate(api_client, workspace.actors, workspace.actors.student)
    resumed = await api_client.post(
        f"/api/v1/stages/{stages[0]}/resume", json=decision(5, version_id)
    )
    assert resumed.status_code == 200 and resumed.json()["stage"]["status"] == "in_progress"
    assert (
        await api_client.put(base, headers=lease, json=save_payload(workspace, 2, "Исправлено"))
    ).status_code == 200
    second = await submit(api_client, stages[0], lease, 6, 3)
    stage = second["stage"]
    assert isinstance(stage, dict)
    next_id = stage["submitted_version_id"]
    assert next_id != version_id and second["revision"] == 7
    authenticate(api_client, workspace.actors, workspace.actors.owner)
    # A decision from a previously opened review cannot confirm the new submission.
    assert (
        await api_client.post(f"/api/v1/stages/{stages[0]}/confirm", json=decision(7, version_id))
    ).status_code == 409
    confirmed = await api_client.post(
        f"/api/v1/stages/{stages[0]}/confirm", json=decision(7, next_id)
    )
    assert confirmed.status_code == 200, confirmed.text
    thesis = (await api_client.get(f"/api/v1/theses/{workspace.thesis_id}")).json()
    assert thesis["progress_percent"] == 50 and thesis["completed_stages"] == 1
    assert (
        await api_client.post(
            f"/api/v1/stages/{stages[0]}/request-changes", json=decision(8, next_id)
        )
    ).status_code == 409
    events = (await api_client.get(f"/api/v1/stages/{stages[0]}/history")).json()["items"]
    assert [item["kind"] for item in events] == [
        "created",
        "submitted",
        "changes_requested",
        "resumed",
        "submitted",
        "confirmed",
    ]
    assert [item["version_id"] for item in events[1:]] == [version_id] * 3 + [next_id] * 2
    assert events[2]["reason"] == "Уточнить выводы"
    history = await api_client.get(f"/api/v1/stages/{stages[0]}/submissions")
    assert history.headers["cache-control"] == "no-store"
    assert [item["version_id"] for item in history.json()["items"]] == [next_id, version_id]
    assert (
        len(
            (
                await api_client.get(f"/api/v1/stages/{stages[0]}/submissions?limit=1&offset=1")
            ).json()["items"]
        )
        == 1
    )
    assert (await api_client.get(version_path)).json() == original
    authenticate(api_client, workspace.actors, workspace.actors.student)
    # Completion remains terminal, but the next stage can use a new working draft.
    assert (
        await api_client.put(
            base, headers=lease, json=save_payload(workspace, 3, "Следующая глава")
        )
    ).status_code == 200
    assert (
        await api_client.post(
            f"/api/v1/stages/{stages[0]}/submit",
            headers=lease,
            json={"expected_revision": 8, "expected_document_revision": 4},
        )
    ).status_code == 409
    await submit(api_client, stages[1], lease, 8, 4)


async def test_review_blocks_all_document_replacement_paths_without_side_effects(
    api_client: AsyncClient,
    workspace: Workspace,
) -> None:
    stage = (await stage_plan(api_client, workspace))[0]
    lease = await acquire(api_client, workspace)
    submission = await submit(api_client, stage, lease, 2)
    base = f"/api/v1/documents/{workspace.document_id}"
    before = (await api_client.get(base)).json()
    versions = (await api_client.get(f"{base}/versions")).json()
    action_stage = submission["stage"]
    assert isinstance(action_stage, dict)
    version_id = action_stage["submitted_version_id"]
    responses = [
        await api_client.put(base, headers=lease, json=save_payload(workspace)),
        await api_client.post(
            f"{base}/restore",
            headers=lease,
            json={"version_id": version_id, "expected_revision": 1},
        ),
        await api_client.post(
            f"{base}/apply-formatting",
            headers=lease,
            json={
                "expected_revision": 1,
                "template_version_id": workspace.template_version_id,
                "confirm_apply": True,
            },
        ),
        await api_client.post(
            f"{base}/import",
            headers={
                **lease,
                "Content-Type": DOCX_MEDIA_TYPE,
            },
            params={"expected_revision": "1", "confirm_replace": "true"},
            content=docx(paragraph("Замена")),
        ),
    ]
    assert [response.status_code for response in responses] == [409] * 4, [
        response.text for response in responses
    ]
    assert (await api_client.get(base)).json() == before
    assert (await api_client.get(f"{base}/versions")).json() == versions
    assert (await api_client.get(f"{base}/imports")).json()["items"] == []
    # Reviewing does not disable read-only export or explicit snapshots.
    assert (
        await api_client.post(
            f"/api/v1/document-versions/{version_id}/exports", json={"format": "docx"}
        )
    ).status_code == 200
    await snapshot(api_client, workspace, lease, 1)
    authenticate(api_client, workspace.actors, workspace.actors.owner)
    assert (
        await api_client.patch(
            f"/api/v1/stages/{stage}",
            json={"expected_revision": 3, "name": "Смена", "position": 1, "due_date": "2027-05-01"},
        )
    ).status_code == 409


async def test_review_roles_isolation_validation_and_expired_lease(
    api_client: AsyncClient,
    workspace: Workspace,
    db_session: AsyncSession,
) -> None:
    stage = (await stage_plan(api_client, workspace))[0]
    lease = await acquire(api_client, workspace)
    body = {"expected_revision": 2, "expected_document_revision": 1}
    path = f"/api/v1/stages/{stage}"
    for user in (workspace.actors.peer, workspace.actors.outsider, workspace.actors.other):
        authenticate(api_client, workspace.actors, user)
        assert (await api_client.post(f"{path}/submit", headers=lease, json=body)).status_code in (
            403,
            404,
        )
        assert (await api_client.get(f"{path}/submissions")).status_code == 404
        assert (
            await api_client.post(f"{path}/confirm", json=decision(2, uuid4().hex))
        ).status_code in (403, 404)
    authenticate(api_client, workspace.actors, workspace.actors.owner)
    assert (await api_client.post(f"{path}/submit", headers=lease, json=body)).status_code == 403
    authenticate(api_client, workspace.actors, workspace.actors.student)
    assert (
        await api_client.post(f"{path}/confirm", json=decision(2, uuid4().hex))
    ).status_code == 403
    assert (
        await api_client.post(
            f"{path}/submit", headers=lease, json={**body, "expected_revision": 1}
        )
    ).status_code == 409
    assert (
        await api_client.post(
            f"{path}/submit", headers=lease, json={**body, "expected_document_revision": 2}
        )
    ).status_code == 409
    assert (
        await api_client.post(f"{path}/submit", headers={"X-Edit-Lease": str(uuid4())}, json=body)
    ).status_code == 409
    assert (
        await api_client.post(
            f"{path}/submit", headers=lease, json={**body, "expected_revision": True}
        )
    ).status_code == 422
    assert (
        await api_client.post(f"{path}/submit", headers=lease, json={**body, "status": "completed"})
    ).status_code == 422
    assert (
        await api_client.post(f"/api/v1/stages/{uuid4()}/submit", headers=lease, json=body)
    ).status_code == 404
    api_client.headers["X-CSRF-Protection"] = ""
    assert (await api_client.post(f"{path}/submit", headers=lease, json=body)).status_code == 403
    api_client.headers["X-CSRF-Protection"] = "1"
    await db_session.execute(
        update(DocumentEditLease)
        .where(DocumentEditLease.document_id == UUID(workspace.document_id))
        .values(
            acquired_at=datetime.now(UTC) - timedelta(minutes=2),
            expires_at=datetime.now(UTC) - timedelta(minutes=1),
        )
    )
    await db_session.commit()
    assert (await api_client.post(f"{path}/submit", headers=lease, json=body)).status_code == 409
    assert (await api_client.get(f"{path}/submissions")).json()["items"] == []
    assert (await api_client.get(f"/api/v1/documents/{workspace.document_id}/versions")).json()[
        "items"
    ] == []
    api_client.cookies.clear()
    assert (await api_client.post(f"{path}/submit", headers=lease, json=body)).status_code == 401


async def test_direct_resubmission_and_multiple_reviews_keep_document_locked_until_all_returned(
    api_client: AsyncClient,
    workspace: Workspace,
) -> None:
    stages = await stage_plan(api_client, workspace, 2)
    lease = await acquire(api_client, workspace)
    first = await submit(api_client, stages[0], lease, 3)
    second = await submit(api_client, stages[1], lease, 4)
    first_stage, second_stage = first["stage"], second["stage"]
    assert isinstance(first_stage, dict) and isinstance(second_stage, dict)
    authenticate(api_client, workspace.actors, workspace.actors.owner)
    returned = await api_client.post(
        f"/api/v1/stages/{stages[0]}/request-changes",
        json=decision(5, first_stage["submitted_version_id"]),
    )
    assert returned.status_code == 200
    authenticate(api_client, workspace.actors, workspace.actors.student)
    base = f"/api/v1/documents/{workspace.document_id}"
    assert (
        await api_client.put(base, headers=lease, json=save_payload(workspace))
    ).status_code == 409
    authenticate(api_client, workspace.actors, workspace.actors.owner)
    returned = await api_client.post(
        f"/api/v1/stages/{stages[1]}/request-changes",
        json=decision(6, second_stage["submitted_version_id"]),
    )
    assert returned.status_code == 200
    authenticate(api_client, workspace.actors, workspace.actors.student)
    assert (
        await api_client.put(base, headers=lease, json=save_payload(workspace))
    ).status_code == 200
    resubmitted = await submit(api_client, stages[0], lease, 7, 2)
    item = resubmitted["stage"]
    assert isinstance(item, dict)
    assert (
        item["status"] == "in_review"
        and item["submitted_version_id"] != first_stage["submitted_version_id"]
    )
    events = (await api_client.get(f"/api/v1/stages/{stages[0]}/history")).json()["items"]
    assert [event["kind"] for event in events] == [
        "created",
        "submitted",
        "changes_requested",
        "submitted",
    ]


async def test_review_and_comment_sources_are_immutable_in_postgresql(
    api_client: AsyncClient,
    workspace: Workspace,
    db_session: AsyncSession,
) -> None:
    stage = (await stage_plan(api_client, workspace))[0]
    lease = await acquire(api_client, workspace)
    result = await submit(api_client, stage, lease, 2)
    item = result["stage"]
    assert isinstance(item, dict)
    version_id = item["submitted_version_id"]
    authenticate(api_client, workspace.actors, workspace.actors.owner)
    # The initial empty document cannot have an anchored text remark. Return,
    # write a draft, and comment on its new immutable version instead.
    assert (
        await api_client.post(
            f"/api/v1/stages/{stage}/request-changes", json=decision(3, version_id)
        )
    ).status_code == 200
    authenticate(api_client, workspace.actors, workspace.actors.student)
    assert (
        await api_client.put(
            f"/api/v1/documents/{workspace.document_id}",
            headers=lease,
            json=save_payload(workspace),
        )
    ).status_code == 200
    version = await snapshot(api_client, workspace, lease, 2)
    authenticate(api_client, workspace.actors, workspace.actors.owner)
    created = await api_client.post(
        f"/api/v1/document-versions/{version['id']}/comments",
        json={
            "body": "Уточнить",
            "quote": "Первая",
            "anchor": {"block_id": "0", "offset_start": 0, "offset_end": 6},
        },
    )
    assert created.status_code == 201, created.text
    comment_id = UUID(created.json()["id"])
    statements = [
        update(StageEvent).where(StageEvent.stage_id == UUID(stage)).values(kind="updated"),
        update(StageSubmission)
        .where(StageSubmission.stage_id == UUID(stage))
        .values(thesis_revision=99),
        update(Comment).where(Comment.id == comment_id).values(quote="Подмена"),
        update(Comment).where(Comment.id == comment_id).values(body="Подмена"),
        update(CommentEvent).where(CommentEvent.comment_id == comment_id).values(status="resolved"),
    ]
    for statement in statements:
        with pytest.raises(DBAPIError):
            async with db_session.begin_nested():
                await db_session.execute(statement)
    assert (
        await db_session.scalar(select(Comment.quote).where(Comment.id == comment_id))
    ) == "Первая"
