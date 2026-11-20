import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, timedelta
from threading import Barrier
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from httpx import AsyncClient
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.database import create_engine, create_session_factory
from app.core.models import (
    GroupMembership,
    StageEvent,
    StageStatus,
    SupervisorGroup,
    Thesis,
    ThesisStage,
    User,
)
from app.main import create_app
from tests.integration.actors import Actors, authenticate, make_actors, seed_actors

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture
async def actors(db_session: AsyncSession) -> Actors:
    result = make_actors()
    await seed_actors(db_session, result)
    return result


def thesis_data(student_id: UUID) -> dict[str, str]:
    return {
        "student_id": str(student_id),
        "title": "  Сопровождение ВКР  ",
        "start_date": "2026-01-01",
        "due_date": "2027-06-30",
    }


def stage_data(
    revision: int = 1, position: int = 1, name: str = "Введение"
) -> dict[str, str | int]:
    return {
        "name": name,
        "position": position,
        "due_date": "2027-01-31",
        "expected_revision": revision,
    }


async def create_thesis(client: AsyncClient, actors: Actors) -> UUID:
    authenticate(client, actors, actors.owner)
    response = await client.post("/api/v1/theses", json=thesis_data(actors.student.id))
    assert response.status_code == 201, response.text
    return UUID(response.json()["id"])


async def test_thesis_creation_membership_uniqueness_and_visibility(
    api_client: AsyncClient, actors: Actors
) -> None:
    authenticate(api_client, actors, actors.owner)
    for user in (actors.free, actors.outsider, actors.owner):
        response = await api_client.post("/api/v1/theses", json=thesis_data(user.id))
        assert response.status_code == 404
    thesis_id = await create_thesis(api_client, actors)
    response = await api_client.get(f"/api/v1/theses/{thesis_id}")
    thesis = response.json()
    assert response.headers["cache-control"] == "no-store"
    assert thesis["title"] == "Сопровождение ВКР"
    assert thesis["student_id"] == str(actors.student.id)
    assert thesis["supervisor_id"] == str(actors.owner.id)
    assert thesis["revision"] == 1
    assert thesis["total_stages"] == thesis["completed_stages"] == 0
    assert thesis["progress_percent"] is None
    assert (
        await api_client.post("/api/v1/theses", json=thesis_data(actors.student.id))
    ).status_code == 409
    for user, visible in (
        (actors.owner, True),
        (actors.student, True),
        (actors.other, False),
        (actors.peer, False),
        (actors.outsider, False),
    ):
        authenticate(api_client, actors, user)
        listing = await api_client.get("/api/v1/theses")
        assert listing.status_code == 200
        assert listing.headers["cache-control"] == "no-store"
        assert [item["id"] for item in listing.json()["items"]] == (
            [str(thesis_id)] if visible else []
        )
        for target in (thesis_id, uuid4()):
            expected = 200 if visible and target == thesis_id else 404
            assert (await api_client.get(f"/api/v1/theses/{target}")).status_code == expected
            assert (await api_client.get(f"/api/v1/theses/{target}/stages")).status_code == expected


async def test_stage_configuration_order_audit_and_stale_revision(
    api_client: AsyncClient, actors: Actors
) -> None:
    thesis_id = await create_thesis(api_client, actors)
    path = f"/api/v1/theses/{thesis_id}/stages"
    first = await api_client.post(path, json=stage_data())
    assert first.status_code == 201, first.text
    assert first.json()["revision"] == 2
    first_id = first.json()["items"][0]["id"]
    second = await api_client.post(path, json=stage_data(2, 1, "  Теория  "))
    assert second.status_code == 201, second.text
    second_id = second.json()["items"][0]["id"]
    assert [stage["id"] for stage in second.json()["items"]] == [second_id, first_id]
    assert [stage["position"] for stage in second.json()["items"]] == [1, 2]
    update = {**stage_data(3, 1, "Новое введение"), "due_date": "2027-02-01"}
    response = await api_client.patch(f"/api/v1/stages/{first_id}", json=update)
    assert response.status_code == 200, response.text
    plan = response.json()
    assert plan["revision"] == 4
    assert [stage["id"] for stage in plan["items"]] == [first_id, second_id]
    assert all(stage["status"] == "in_progress" for stage in plan["items"])
    # A no-op with a current revision does not manufacture audit events/revisions.
    assert (
        await api_client.patch(
            f"/api/v1/stages/{first_id}", json={**update, "expected_revision": 4}
        )
    ).json() == plan
    stale = await api_client.patch(f"/api/v1/stages/{first_id}", json=update)
    assert stale.status_code == 409
    assert (await api_client.post(path, json=stage_data(3, 3))).status_code == 409
    assert (await api_client.get(path)).json() == plan
    for user in (actors.owner, actors.student):
        authenticate(api_client, actors, user)
        history = await api_client.get(f"/api/v1/stages/{first_id}/history")
        assert history.status_code == 200
        assert history.headers["cache-control"] == "no-store"
        events = history.json()["items"]
        assert [event["thesis_revision"] for event in events] == [2, 3, 4]
        assert [event["kind"] for event in events] == ["created", "updated", "updated"]
        assert all(event["actor_id"] == str(actors.owner.id) for event in events)
        assert events[0]["before"] is None
        assert events[0]["after"] == {
            "name": "Введение",
            "position": 1,
            "due_date": "2027-01-31",
            "status": "in_progress",
        }
        assert events[1]["before"] == events[0]["after"]
        assert events[1]["after"]["position"] == 2
        assert events[2]["before"] == events[1]["after"]
        assert events[2]["after"]["name"] == "Новое введение"
        page = (await api_client.get(f"/api/v1/stages/{first_id}/history?limit=1&offset=1")).json()
        assert page["items"] == [events[1]]


@pytest.mark.parametrize("role", ["guest", "student", "other", "peer"])
async def test_stage_and_thesis_mutation_access(
    api_client: AsyncClient, actors: Actors, role: str
) -> None:
    thesis_id = await create_thesis(api_client, actors)
    stage = await api_client.post(f"/api/v1/theses/{thesis_id}/stages", json=stage_data())
    stage_id = stage.json()["items"][0]["id"]
    api_client.cookies.clear()
    user = {"student": actors.student, "peer": actors.peer, "other": actors.other}.get(role)
    if user:
        authenticate(api_client, actors, user)
    expected = 401 if user is None else (404 if role == "other" else 403)
    for method, path in (("POST", f"/theses/{thesis_id}/stages"), ("PATCH", f"/stages/{stage_id}")):
        assert (
            await api_client.request(method, f"/api/v1{path}", json=stage_data(2))
        ).status_code == expected
    assert (
        await api_client.post("/api/v1/theses", json=thesis_data(actors.peer.id))
    ).status_code == (401 if user is None else (404 if role == "other" else 403))
    history_status = 401 if user is None else (200 if role == "student" else 404)
    assert (
        await api_client.get(f"/api/v1/stages/{stage_id}/history")
    ).status_code == history_status
    assert (await api_client.get(f"/api/v1/stages/{uuid4()}/history")).status_code == (
        401 if user is None else 404
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"title": " \n\t "},
        {"title": "x" * 501},
        {"due_date": "2025-01-01"},
        {"start_date": "invalid"},
        {"supervisor_id": str(uuid4())},
        {"revision": 50},
    ],
)
async def test_thesis_validation(
    api_client: AsyncClient, actors: Actors, changes: dict[str, object]
) -> None:
    authenticate(api_client, actors, actors.owner)
    response = await api_client.post(
        "/api/v1/theses", json={**thesis_data(actors.student.id), **changes}
    )
    assert response.status_code == 422
    assert (await api_client.get("/api/v1/theses")).json()["items"] == []


@pytest.mark.parametrize(
    "changes",
    [
        {"name": " \n "},
        {"name": "x" * 256},
        {"due_date": "2025-12-31"},
        {"due_date": "2027-07-01"},
        {"due_date": "invalid"},
        {"position": 0},
        {"position": 2},
        {"position": True},
        {"position": "1"},
        {"expected_revision": 0},
        {"expected_revision": True},
        {"expected_revision": "1"},
        {"status": "completed"},
        {"weight": 1},
        {"required": False},
        {"thesis_id": str(uuid4())},
    ],
)
async def test_stage_validation_is_atomic(
    api_client: AsyncClient, actors: Actors, changes: dict[str, object], db_session: AsyncSession
) -> None:
    thesis_id = await create_thesis(api_client, actors)
    path = f"/api/v1/theses/{thesis_id}/stages"
    assert (await api_client.post(path, json={**stage_data(), **changes})).status_code == 422
    plan = (await api_client.get(path)).json()
    assert plan["items"] == [] and plan["revision"] == 1
    assert await db_session.scalar(select(func.count()).select_from(StageEvent)) == 0


async def test_patch_validation_csrf_and_pagination(
    api_client: AsyncClient, actors: Actors
) -> None:
    thesis_id = await create_thesis(api_client, actors)
    path = f"/api/v1/theses/{thesis_id}/stages"
    plan = (await api_client.post(path, json=stage_data())).json()
    stage_id = plan["items"][0]["id"]
    for changes in ({"position": 2}, {"due_date": "2028-01-01"}, {"status": "in_review"}):
        assert (
            await api_client.patch(f"/api/v1/stages/{stage_id}", json={**stage_data(2), **changes})
        ).status_code == 422
    assert (await api_client.get(path)).json() == plan
    assert (
        await api_client.patch(f"/api/v1/stages/{uuid4()}", json=stage_data(2))
    ).status_code == 404
    for query in ("limit=0", "limit=101", "offset=-1", f"offset={2**63}", "unexpected=1"):
        for target in (
            "/api/v1/theses",
            f"/api/v1/stages/{stage_id}/history",
            f"/api/v1/supervisor-groups/{actors.group.id}/progress",
        ):
            assert (await api_client.get(f"{target}?{query}")).status_code == 422
    del api_client.headers["X-CSRF-Protection"]
    for method, target, payload in (
        ("POST", "/api/v1/theses", thesis_data(actors.peer.id)),
        ("POST", path, stage_data(2, 2)),
        ("PATCH", f"/api/v1/stages/{stage_id}", stage_data(2)),
    ):
        assert (await api_client.request(method, target, json=payload)).status_code == 403


async def test_group_progress_includes_unconfigured_students_and_is_isolated(
    api_client: AsyncClient, actors: Actors, db_session: AsyncSession
) -> None:
    thesis_id = await create_thesis(api_client, actors)
    path = f"/api/v1/supervisor-groups/{actors.group.id}/progress"
    initial = await api_client.get(path)
    assert initial.status_code == 200
    assert initial.headers["cache-control"] == "no-store"
    items = initial.json()["items"]
    assert [item["student"]["id"] for item in items] == [
        str(actors.student.id),
        str(actors.peer.id),
    ]
    assert items[0]["thesis"]["progress_percent"] is None
    assert items[1]["thesis"] is None and items[1]["stages"] == []
    today = datetime.now(UTC).date()
    thesis = await db_session.get(Thesis, thesis_id)
    assert thesis is not None
    thesis.start_date, thesis.due_date = today - timedelta(days=100), today - timedelta(days=1)
    # States from the future review workflow are fixtures, never HTTP status mutations.
    for position, state in enumerate(StageStatus, start=1):
        db_session.add(
            ThesisStage(
                thesis_id=thesis_id,
                name=state.value,
                position=position,
                due_date=today - timedelta(days=1),
                status=state,
            )
        )
    await db_session.commit()
    result = (await api_client.get(path)).json()
    summary = result["items"][0]["thesis"]
    assert summary["total_stages"] == 4 and summary["completed_stages"] == 1
    assert summary["progress_percent"] == 25
    assert summary["overdue_stages"] == 3 and summary["is_overdue"] is True
    assert [stage["is_overdue"] for stage in result["items"][0]["stages"]] == [
        True,
        True,
        True,
        False,
    ]
    for offset, student in enumerate((actors.student, actors.peer)):
        page = (await api_client.get(path, params={"limit": 1, "offset": offset})).json()
        assert len(page["items"]) == 1 and page["items"][0]["student"]["id"] == str(student.id)
    assert (await api_client.get(f"/api/v1/theses/{thesis_id}")).json() == summary
    assert (await api_client.get("/api/v1/theses")).json()["items"] == [summary]
    assert "password" not in str(result)
    for user, status_code in ((actors.other, 404), (actors.student, 403), (actors.peer, 403)):
        authenticate(api_client, actors, user)
        assert (await api_client.get(path)).status_code == status_code
        assert (
            await api_client.get(f"/api/v1/supervisor-groups/{uuid4()}/progress")
        ).status_code == status_code
    api_client.cookies.clear()
    assert (await api_client.get(path)).status_code == 401


@pytest.mark.parametrize("state", [StageStatus.IN_REVIEW, StageStatus.COMPLETED])
async def test_review_and_completed_stage_plan_cannot_be_rewritten(
    api_client: AsyncClient, actors: Actors, db_session: AsyncSession, state: StageStatus
) -> None:
    thesis_id = await create_thesis(api_client, actors)
    path = f"/api/v1/theses/{thesis_id}/stages"
    plan = (await api_client.post(path, json=stage_data())).json()
    stage_id = UUID(plan["items"][0]["id"])
    stage = await db_session.get(ThesisStage, stage_id)
    assert stage is not None
    stage.status = state
    await db_session.commit()
    before = (await api_client.get(path)).json()
    for method, target, data in (
        ("POST", path, stage_data(2, 2)),
        ("PATCH", f"/api/v1/stages/{stage_id}", stage_data(2)),
    ):
        assert (await api_client.request(method, target, json=data)).status_code == 409
    assert (await api_client.get(path)).json() == before


async def test_database_constraints_preserve_plan_and_history(
    api_client: AsyncClient, actors: Actors, db_session: AsyncSession
) -> None:
    thesis_id = await create_thesis(api_client, actors)
    plan = (await api_client.post(f"/api/v1/theses/{thesis_id}/stages", json=stage_data())).json()
    stage_id = UUID(plan["items"][0]["id"])
    for statement in (
        delete(ThesisStage).where(ThesisStage.id == stage_id),
        delete(Thesis).where(Thesis.id == thesis_id),
        delete(GroupMembership).where(GroupMembership.student_id == actors.student.id),
    ):
        with pytest.raises(IntegrityError):
            async with db_session.begin_nested():
                await db_session.execute(statement)
    assert (await api_client.get(f"/api/v1/theses/{thesis_id}/stages")).json() == plan


@pytest.mark.parametrize("operation", ["thesis", "create_stage", "update_stage"])
def test_concurrent_writes_have_one_winner(
    migrated_database: None, integration_settings: Settings, operation: str
) -> None:
    actors = make_actors()
    thesis_id, stage_id = uuid4(), uuid4()

    async def prepare_or_cleanup(*, cleanup: bool) -> None:
        engine = create_engine(integration_settings)
        try:
            async with create_session_factory(engine)() as session:
                if not cleanup:
                    await seed_actors(session, actors)
                    if operation != "thesis":
                        session.add(
                            Thesis(
                                id=thesis_id,
                                supervisor_id=actors.owner.id,
                                **{
                                    **thesis_data(actors.student.id),
                                    "student_id": actors.student.id,
                                    "title": "Тестовая ВКР",
                                    "start_date": date(2026, 1, 1),
                                    "due_date": date(2027, 6, 30),
                                },
                            )
                        )
                        await session.flush()
                        if operation == "update_stage":
                            session.add(
                                ThesisStage(
                                    id=stage_id,
                                    thesis_id=thesis_id,
                                    name="Исходный",
                                    position=1,
                                    due_date=date(2027, 1, 31),
                                )
                            )
                    await session.commit()
                else:
                    thesis_ids = select(Thesis.id).where(
                        Thesis.student_id.in_([user.id for user in actors.users])
                    )
                    stage_ids = select(ThesisStage.id).where(ThesisStage.thesis_id.in_(thesis_ids))
                    await session.execute(
                        delete(StageEvent).where(StageEvent.stage_id.in_(stage_ids))
                    )
                    await session.execute(
                        delete(ThesisStage).where(ThesisStage.thesis_id.in_(thesis_ids))
                    )
                    await session.execute(delete(Thesis).where(Thesis.id.in_(thesis_ids)))
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
                    await session.commit()
        finally:
            await engine.dispose()

    try:
        asyncio.run(prepare_or_cleanup(cleanup=False))
        with (
            TestClient(
                create_app(integration_settings), headers={"X-CSRF-Protection": "1"}
            ) as first,
            TestClient(
                create_app(integration_settings), headers={"X-CSRF-Protection": "1"}
            ) as second,
        ):
            for client in (first, second):
                authenticate(client, actors, actors.owner)
            barrier = Barrier(2)

            def write(client: TestClient, name: str) -> tuple[int, str]:
                barrier.wait(timeout=10)
                if operation == "thesis":
                    response = client.post(
                        "/api/v1/theses", json={**thesis_data(actors.student.id), "title": name}
                    )
                elif operation == "create_stage":
                    response = client.post(
                        f"/api/v1/theses/{thesis_id}/stages", json=stage_data(name=name)
                    )
                else:
                    response = client.patch(
                        f"/api/v1/stages/{stage_id}", json=stage_data(name=name)
                    )
                return response.status_code, name

            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = [
                    pool.submit(write, client, name)
                    for client, name in ((first, "Первый"), (second, "Второй"))
                ]
                results = [future.result(timeout=20) for future in futures]
            success = 200 if operation == "update_stage" else 201
            assert sorted(code for code, _ in results) == [success, 409]
            winner = next(name for code, name in results if code == success)
            if operation == "thesis":
                items = first.get("/api/v1/theses").json()["items"]
                assert len(items) == 1 and items[0]["title"] == winner
            else:
                plan = first.get(f"/api/v1/theses/{thesis_id}/stages").json()
                assert plan["revision"] == 2 and len(plan["items"]) == 1
                assert plan["items"][0]["name"] == winner
                events = first.get(f"/api/v1/stages/{plan['items'][0]['id']}/history").json()[
                    "items"
                ]
                assert len(events) == 1 and events[0]["after"]["name"] == winner
    finally:
        asyncio.run(prepare_or_cleanup(cleanup=True))
