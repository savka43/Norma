from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.models import CheckStatus, PlagiarismCheck
from app.core.models.plagiarism import ACTIVE_CHECK_SQL

ACTIVE = text(ACTIVE_CHECK_SQL)


@dataclass(frozen=True)
class Claim:
    check: PlagiarismCheck
    token: UUID


async def active_check_id(session: AsyncSession, version_id: UUID) -> UUID | None:
    return await session.scalar(
        select(PlagiarismCheck.id).where(PlagiarismCheck.version_id == version_id, ACTIVE)
    )


async def list_checks(
    session: AsyncSession, version_id: UUID, limit: int, offset: int
) -> list[PlagiarismCheck]:
    return list(
        await session.scalars(
            select(PlagiarismCheck)
            .where(PlagiarismCheck.version_id == version_id)
            .order_by(PlagiarismCheck.created_at.desc(), PlagiarismCheck.id.desc())
            .limit(limit)
            .offset(offset)
        )
    )


def fail(check: PlagiarismCheck, now: datetime, code: str, detail: str) -> None:
    check.status = CheckStatus.FAILED
    check.error_code, check.error_detail = code, detail
    check.finished_at, check.updated_at = now, now
    check.claim_id = check.claim_until = None


async def claim_due(
    session: AsyncSession, now: datetime, claim_seconds: float, check_seconds: int
) -> Claim | None:
    check = await session.scalar(
        select(PlagiarismCheck)
        .where(
            ACTIVE,
            PlagiarismCheck.next_run_at <= now,
            or_(PlagiarismCheck.claim_until.is_(None), PlagiarismCheck.claim_until <= now),
        )
        .order_by(PlagiarismCheck.next_run_at, PlagiarismCheck.id)
        .limit(1)
        .with_for_update(skip_locked=True)
        .execution_options(populate_existing=True)
    )
    if check is None:
        return None
    if check.status in {CheckStatus.UPLOADING, CheckStatus.STARTING}:
        fail(
            check, now, "interrupted", "Worker stopped during an unconfirmed Antiplagiat operation"
        )
        await session.commit()
        return None
    if check.deadline_at is not None and check.deadline_at <= now:
        fail(check, now, "check_timeout", "Antiplagiat did not complete within the configured time")
        await session.commit()
        return None
    if check.status == CheckStatus.QUEUED:
        check.status = CheckStatus.UPLOADING
    elif check.status == CheckStatus.UPLOADED:
        check.status = CheckStatus.STARTING
        check.deadline_at = now + timedelta(seconds=check_seconds)
    token = uuid4()
    check.claim_id = token
    check.claim_until = now + timedelta(seconds=claim_seconds)
    check.updated_at = now
    await session.commit()
    return Claim(check, token)


async def lock_claim(session: AsyncSession, claim: Claim) -> PlagiarismCheck | None:
    return await session.scalar(
        select(PlagiarismCheck)
        .where(PlagiarismCheck.id == claim.check.id, PlagiarismCheck.claim_id == claim.token)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
