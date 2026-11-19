import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from threading import Barrier
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from httpx import AsyncClient
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.database import create_engine, create_session_factory
from app.core.models import GroupMembership, SupervisorGroup, User, UserRole
from app.core.security import hash_password
from app.main import create_app

pytestmark = pytest.mark.integration
PASSWORD = "Synthetic-groups-password-123"


@dataclass(frozen=True)
class Account:
    id: UUID
    email: str


@dataclass(frozen=True)
class Accounts:
    owner: Account
    other: Account
    student: Account
    second: Account


def make_account(role: UserRole, email: str, full_name: str, password_hash: str) -> User:
    return User(
        id=uuid4(),
        email=email,
        full_name=full_name,
        password_hash=password_hash,
        role=role,
        academic_group="ИДБ-23-08" if role == UserRole.STUDENT else None,
        position="Доцент" if role == UserRole.SUPERVISOR else None,
        department="Информационные системы" if role == UserRole.SUPERVISOR else None,
    )


@pytest_asyncio.fixture
async def accounts(db_session: AsyncSession) -> Accounts:
    password_hash = hash_password(PASSWORD)
    users = [
        make_account(UserRole.SUPERVISOR, "owner@example.com", "Руководитель", password_hash),
        make_account(
            UserRole.SUPERVISOR, "other@example.com", "Студент Руководитель", password_hash
        ),
        make_account(UserRole.STUDENT, "anna@example.com", "Анна Студент %_/", password_hash),
        make_account(UserRole.STUDENT, "boris@example.com", "Борис Студент", password_hash),
    ]
    db_session.add_all(users)
    await db_session.commit()
    return Accounts(*(Account(user.id, user.email) for user in users))


async def login(client: AsyncClient, account: Account) -> None:
    response = await client.post(
        "/api/v1/auth/login", json={"email": account.email, "password": PASSWORD}
    )
    assert response.status_code == 200


async def create_group(client: AsyncClient, name: str = "Группа ВКР") -> UUID:
    response = await client.post(
        "/api/v1/supervisor-groups", json={"name": name, "academic_year": 2026}
    )
    assert response.status_code == 201
    return UUID(response.json()["id"])


async def test_form_group_from_self_registered_student(
    api_client: AsyncClient, accounts: Accounts, db_session: AsyncSession
) -> None:
    registration = await api_client.post(
        "/api/v1/auth/register",
        json={
            "email": "new-student@example.com",
            "password": PASSWORD,
            "full_name": "Новый Студент",
            "academic_group": "ИДБ-24-01",
        },
    )
    assert registration.status_code == 201
    student_id = registration.json()["id"]
    await login(api_client, accounts.owner)
    response = await api_client.post(
        "/api/v1/supervisor-groups",
        json={
            "name": "  Выпуск 2027  ",
            "academic_year": 2026,
        },
    )
    assert response.status_code == 201
    group = response.json()
    assert group["name"] == "Выпуск 2027"
    assert group["academic_year"] == 2026
    assert group["supervisor_id"] == str(accounts.owner.id)
    assert group["created_at"]
    group_id = group["id"]
    assert (await api_client.get(f"/api/v1/supervisor-groups/{group_id}")).json() == group
    members_path = f"/api/v1/supervisor-groups/{group_id}/students"
    assert (await api_client.get(members_path)).json()["items"] == []
    response = await api_client.post(members_path, json={"student_id": student_id})
    assert response.status_code == 201
    assert response.json()["student_id"] == student_id
    assert response.json()["group_id"] == group_id and response.json()["joined_at"]
    roster = await api_client.get(members_path)
    assert roster.status_code == 200 and roster.headers["cache-control"] == "no-store"
    assert roster.json()["items"] == [
        {
            "id": student_id,
            "full_name": "Новый Студент",
            "email": "new-student@example.com",
            "academic_group": "ИДБ-24-01",
        }
    ]
    membership = await db_session.get(GroupMembership, UUID(student_id))
    assert membership is not None and str(membership.group_id) == group_id
    user = await db_session.get(User, UUID(student_id))
    assert user is not None and user.academic_group == "ИДБ-24-01"


async def test_foreign_group_is_hidden_and_cannot_be_modified(
    api_client: AsyncClient, accounts: Accounts, db_session: AsyncSession
) -> None:
    await login(api_client, accounts.owner)
    group_id = await create_group(api_client)
    await login(api_client, accounts.other)
    other_id = await create_group(api_client, "Другая группа")
    own_groups = await api_client.get("/api/v1/supervisor-groups")
    assert [group["id"] for group in own_groups.json()["items"]] == [str(other_id)]
    assert own_groups.headers["cache-control"] == "no-store"
    for target in (group_id, uuid4()):
        assert (await api_client.get(f"/api/v1/supervisor-groups/{target}")).json() == {
            "detail": "Group not found"
        }
        assert (
            await api_client.get(f"/api/v1/supervisor-groups/{target}/students")
        ).status_code == 404
        response = await api_client.post(
            f"/api/v1/supervisor-groups/{target}/students",
            json={"student_id": str(accounts.student.id)},
        )
        assert response.status_code == 404
    assert await db_session.get(GroupMembership, accounts.student.id) is None


@pytest.mark.parametrize("authenticated", [False, True])
@pytest.mark.parametrize(
    ("method", "path", "payload"),
    [
        ("GET", "/supervisor-groups", None),
        ("POST", "/supervisor-groups", {"name": "Группа", "academic_year": 2026}),
        ("GET", "/supervisor-groups/00000000-0000-0000-0000-000000000001", None),
        ("GET", "/supervisor-groups/00000000-0000-0000-0000-000000000001/students", None),
        (
            "POST",
            "/supervisor-groups/00000000-0000-0000-0000-000000000001/students",
            {"student_id": "00000000-0000-0000-0000-000000000002"},
        ),
        ("GET", "/students?query=Студент", None),
    ],
)
async def test_all_group_routes_require_supervisor(
    api_client: AsyncClient,
    accounts: Accounts,
    authenticated: bool,
    method: str,
    path: str,
    payload: dict[str, str | int] | None,
) -> None:
    if authenticated:
        await login(api_client, accounts.student)
    response = await api_client.request(method, f"/api/v1{path}", json=payload)
    assert response.status_code == (403 if authenticated else 401)


@pytest.mark.parametrize(
    "changes",
    [
        {"name": " \t\n "},
        {"name": "n" * 256},
        {"academic_year": 0},
        {"academic_year": 9999},
        {"academic_year": True},
        {"academic_year": "2026"},
        {"supervisor_id": "00000000-0000-0000-0000-000000000001"},
    ],
)
async def test_group_validation_and_owner_cannot_be_injected(
    api_client: AsyncClient, accounts: Accounts, changes: dict[str, str | int | bool]
) -> None:
    await login(api_client, accounts.owner)
    response = await api_client.post(
        "/api/v1/supervisor-groups",
        json={
            "name": "Группа",
            "academic_year": 2026,
            **changes,
        },
    )
    assert response.status_code == 422
    assert (await api_client.get("/api/v1/supervisor-groups")).json()["items"] == []


async def test_csrf_is_required_for_group_mutations(
    api_client: AsyncClient, accounts: Accounts
) -> None:
    await login(api_client, accounts.owner)
    group_id = await create_group(api_client)
    del api_client.headers["X-CSRF-Protection"]
    response = await api_client.post(
        "/api/v1/supervisor-groups", json={"name": "Группа", "academic_year": 2026}
    )
    assert response.status_code == 403
    response = await api_client.post(
        f"/api/v1/supervisor-groups/{group_id}/students",
        json={"student_id": str(accounts.student.id)},
    )
    assert response.status_code == 403


async def test_duplicate_and_cross_supervisor_assignment_conflict_without_rebinding(
    api_client: AsyncClient, accounts: Accounts, db_session: AsyncSession
) -> None:
    await login(api_client, accounts.owner)
    original = await create_group(api_client)
    second = await create_group(api_client, "Вторая группа")
    payload = {"student_id": str(accounts.student.id)}
    assert (
        await api_client.post(f"/api/v1/supervisor-groups/{original}/students", json=payload)
    ).status_code == 201
    for group_id in (original, second):
        response = await api_client.post(
            f"/api/v1/supervisor-groups/{group_id}/students", json=payload
        )
        assert response.status_code == 409
        assert response.json() == {"detail": "Student already belongs to a group"}
    await login(api_client, accounts.other)
    foreign = await create_group(api_client, "Чужая группа")
    response = await api_client.post(f"/api/v1/supervisor-groups/{foreign}/students", json=payload)
    assert response.status_code == 409
    assert str(original) not in response.text
    stored = await db_session.get(GroupMembership, accounts.student.id)
    assert stored is not None and stored.group_id == original
    assert (await api_client.get(f"/api/v1/supervisor-groups/{foreign}/students")).json()[
        "items"
    ] == []


async def test_only_registered_student_can_be_added(
    api_client: AsyncClient, accounts: Accounts
) -> None:
    await login(api_client, accounts.owner)
    group_id = await create_group(api_client)
    for user_id in (uuid4(), accounts.other.id):
        response = await api_client.post(
            f"/api/v1/supervisor-groups/{group_id}/students", json={"student_id": str(user_id)}
        )
        assert response.status_code == 404
        assert response.json() == {"detail": "Student not found"}
    response = await api_client.post(
        f"/api/v1/supervisor-groups/{group_id}/students",
        json={
            "student_id": str(accounts.student.id),
            "group_id": str(uuid4()),
        },
    )
    assert response.status_code == 422


async def test_search_is_bounded_literal_and_excludes_assigned_students(
    api_client: AsyncClient, accounts: Accounts
) -> None:
    await login(api_client, accounts.owner)
    response = await api_client.get("/api/v1/students", params={"query": "  сТуДеНт  "})
    assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
    assert {item["id"] for item in response.json()["items"]} == {
        str(accounts.student.id),
        str(accounts.second.id),
    }
    assert all(
        set(item) == {"id", "email", "full_name", "academic_group"}
        for item in response.json()["items"]
    )
    email_match = await api_client.get("/api/v1/students", params={"query": "ANNA@EXAMPLE.COM"})
    assert [item["id"] for item in email_match.json()["items"]] == [str(accounts.student.id)]
    literal = await api_client.get("/api/v1/students", params={"query": "%_/"})
    assert [item["id"] for item in literal.json()["items"]] == [str(accounts.student.id)]
    assert (await api_client.get("/api/v1/students", params={"query": "%%%"})).json()["items"] == []
    first = await api_client.get("/api/v1/students", params={"query": "Студент", "limit": 1})
    second = await api_client.get(
        "/api/v1/students", params={"query": "Студент", "limit": 1, "offset": 1}
    )
    assert len(first.json()["items"]) == len(second.json()["items"]) == 1
    assert first.json()["items"][0]["id"] != second.json()["items"][0]["id"]
    group_id = await create_group(api_client)
    await api_client.post(
        f"/api/v1/supervisor-groups/{group_id}/students",
        json={"student_id": str(accounts.student.id)},
    )
    for account in (accounts.owner, accounts.other):
        await login(api_client, account)
        response = await api_client.get("/api/v1/students", params={"query": "Студент"})
        assert [item["id"] for item in response.json()["items"]] == [str(accounts.second.id)]


@pytest.mark.parametrize(
    "query_string",
    [
        "",
        "?query=ab",
        "?query=%20%20%20",
        "?query=student&limit=51",
        "?query=student&limit=0",
        "?query=student&offset=-1",
        "?query=student&offset=9223372036854775808",
        "?query=student&unknown=1",
    ],
)
async def test_invalid_student_search(
    api_client: AsyncClient, accounts: Accounts, query_string: str
) -> None:
    await login(api_client, accounts.owner)
    assert (await api_client.get(f"/api/v1/students{query_string}")).status_code == 422


async def test_group_and_roster_pagination(api_client: AsyncClient, accounts: Accounts) -> None:
    await login(api_client, accounts.owner)
    groups = {await create_group(api_client, name) for name in ("Первая", "Вторая")}
    pages = [
        (
            await api_client.get("/api/v1/supervisor-groups", params={"limit": 1, "offset": offset})
        ).json()
        for offset in (0, 1)
    ]
    assert {UUID(page["items"][0]["id"]) for page in pages} == groups
    group_id = next(iter(groups))
    for account in (accounts.student, accounts.second):
        await api_client.post(
            f"/api/v1/supervisor-groups/{group_id}/students", json={"student_id": str(account.id)}
        )
    pages = [
        (
            await api_client.get(
                f"/api/v1/supervisor-groups/{group_id}/students",
                params={"limit": 1, "offset": offset},
            )
        ).json()
        for offset in (0, 1)
    ]
    assert {page["items"][0]["id"] for page in pages} == {
        str(accounts.student.id),
        str(accounts.second.id),
    }
    for path in ("/api/v1/supervisor-groups", f"/api/v1/supervisor-groups/{group_id}/students"):
        assert (await api_client.get(path, params={"limit": 101})).status_code == 422
        assert (await api_client.get(path, params={"offset": 2**63})).status_code == 422


@pytest.mark.parametrize("same_group", [False, True])
def test_concurrent_assignment_has_one_winner(
    migrated_database: None, integration_settings: Settings, same_group: bool
) -> None:
    # Real requests use distinct sessions/connections and committed synthetic data.
    suffix = uuid4().hex
    password_hash = hash_password(PASSWORD)
    owner = make_account(
        UserRole.SUPERVISOR, f"owner-{suffix}@example.com", "Первый", password_hash
    )
    other = make_account(
        UserRole.SUPERVISOR, f"other-{suffix}@example.com", "Второй", password_hash
    )
    student = make_account(
        UserRole.STUDENT, f"student-{suffix}@example.com", "Студент", password_hash
    )
    first = SupervisorGroup(id=uuid4(), supervisor_id=owner.id, name="Первая", academic_year=2026)
    second = SupervisorGroup(id=uuid4(), supervisor_id=other.id, name="Вторая", academic_year=2026)
    user_ids = [owner.id, other.id, student.id]
    group_ids = [first.id, second.id]

    async def seed_or_cleanup(*, cleanup: bool) -> None:
        engine = create_engine(integration_settings)
        try:
            async with create_session_factory(engine)() as session:
                if cleanup:
                    await session.execute(
                        delete(GroupMembership).where(GroupMembership.student_id == student.id)
                    )
                    await session.execute(
                        delete(SupervisorGroup).where(SupervisorGroup.id.in_(group_ids))
                    )
                    await session.execute(delete(User).where(User.id.in_(user_ids)))
                else:
                    session.add_all([owner, other, student])
                    await session.flush()
                    session.add_all([first, second])
                await session.commit()
        finally:
            await engine.dispose()

    barrier = Barrier(2)
    try:
        asyncio.run(seed_or_cleanup(cleanup=False))
        with (
            TestClient(
                create_app(integration_settings), headers={"X-CSRF-Protection": "1"}
            ) as client1,
            TestClient(
                create_app(integration_settings), headers={"X-CSRF-Protection": "1"}
            ) as client2,
        ):
            for client, email in (
                (client1, owner.email),
                (client2, owner.email if same_group else other.email),
            ):
                assert (
                    client.post(
                        "/api/v1/auth/login", json={"email": email, "password": PASSWORD}
                    ).status_code
                    == 200
                )

            def assign(client: TestClient, group_id: UUID) -> int:
                barrier.wait(timeout=10)
                return client.post(
                    f"/api/v1/supervisor-groups/{group_id}/students",
                    json={"student_id": str(student.id)},
                ).status_code

            with ThreadPoolExecutor(max_workers=2) as pool:
                requests = [
                    pool.submit(assign, client1, first.id),
                    pool.submit(assign, client2, first.id if same_group else second.id),
                ]
                assert sorted(request.result(timeout=20) for request in requests) == [201, 409]
            roster1 = client1.get(f"/api/v1/supervisor-groups/{first.id}/students").json()["items"]
            roster2 = client2.get(
                f"/api/v1/supervisor-groups/{first.id if same_group else second.id}/students"
            ).json()["items"]
            if same_group:
                assert roster1 == roster2 and len(roster1) == 1
            else:
                assert len(roster1) + len(roster2) == 1
    finally:
        asyncio.run(seed_or_cleanup(cleanup=True))
