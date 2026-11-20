from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.models import AuthSession, GroupMembership, SupervisorGroup, User, UserRole
from app.core.security import SESSION_COOKIE_NAME, new_session_token, session_token_hash


@dataclass
class Actors:
    owner: User
    other: User
    student: User
    peer: User
    outsider: User
    free: User
    group: SupervisorGroup
    foreign_group: SupervisorGroup
    tokens: dict[UUID, str]

    @property
    def users(self) -> list[User]:
        return [self.owner, self.other, self.student, self.peer, self.outsider, self.free]


def make_actors() -> Actors:
    suffix = uuid4().hex

    def user(name: str, role: UserRole) -> User:
        return User(
            id=uuid4(),
            email=f"{name}-{suffix}@example.com",
            full_name=name,
            password_hash="unused-synthetic-hash",
            role=role,
            academic_group="ИДБ-23-08" if role == UserRole.STUDENT else None,
            position="Доцент" if role == UserRole.SUPERVISOR else None,
            department="ИС" if role == UserRole.SUPERVISOR else None,
        )

    owner, other = (user(name, UserRole.SUPERVISOR) for name in ("Owner", "Other"))
    student, peer, outsider, free = (
        user(name, UserRole.STUDENT) for name in ("Anna", "Boris", "Outside", "Free")
    )
    return Actors(
        owner,
        other,
        student,
        peer,
        outsider,
        free,
        SupervisorGroup(id=uuid4(), supervisor_id=owner.id, name="Своя", academic_year=2026),
        SupervisorGroup(id=uuid4(), supervisor_id=other.id, name="Чужая", academic_year=2026),
        {},
    )


async def seed_actors(session: AsyncSession, actors: Actors) -> None:
    session.add_all(actors.users)
    await session.flush()
    session.add_all([actors.group, actors.foreign_group])
    await session.flush()
    session.add_all(
        [
            GroupMembership(student_id=actors.student.id, group_id=actors.group.id),
            GroupMembership(student_id=actors.peer.id, group_id=actors.group.id),
            GroupMembership(student_id=actors.outsider.id, group_id=actors.foreign_group.id),
        ]
    )
    for user in actors.users:
        token = new_session_token()
        token_hash = session_token_hash(token)
        assert token_hash is not None
        actors.tokens[user.id] = token
        session.add(
            AuthSession(
                user_id=user.id,
                token_hash=token_hash,
                expires_at=datetime.now(UTC) + timedelta(hours=1),
            )
        )
    await session.commit()
    # Keep fixture identities usable after API conflict handlers roll back their session.
    for entity in [*actors.users, actors.group, actors.foreign_group]:
        session.expunge(entity)


def authenticate(client: AsyncClient | TestClient, actors: Actors, user: User) -> None:
    client.cookies.clear()
    client.cookies.set(SESSION_COOKIE_NAME, actors.tokens[user.id])
