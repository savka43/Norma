from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api_v1.users.schemas import StudentSearchParams
from app.core.models import GroupMembership, User, UserRole


async def search_available_students(
    session: AsyncSession, params: StudentSearchParams
) -> list[User]:
    statement = (
        select(User)
        .where(
            User.role == UserRole.STUDENT,
            ~select(GroupMembership).where(GroupMembership.student_id == User.id).exists(),
            or_(
                User.full_name.icontains(params.query, autoescape=True),
                User.email.icontains(params.query, autoescape=True),
            ),
        )
        .order_by(User.full_name, User.id)
        .limit(params.limit)
        .offset(params.offset)
    )
    return list(await session.scalars(statement))
