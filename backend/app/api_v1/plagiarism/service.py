from datetime import timedelta
from typing import Protocol

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from starlette.concurrency import run_in_threadpool

from app.api_v1.documents.crud import database_now
from app.api_v1.documents.structure import document_text
from app.api_v1.plagiarism import crud
from app.api_v1.plagiarism.client import ProviderError, ProviderStatus
from app.core.config import Settings
from app.core.models import CheckStatus, DocumentVersion, PlagiarismCheck, User


class Provider(Protocol):
    def upload(self, data: bytes, external_user_id: str) -> int: ...

    def start(self, external_id: int) -> None: ...

    def poll(self, external_id: int) -> ProviderStatus: ...


def text_payload(version: DocumentVersion, settings: Settings) -> bytes:
    text = document_text(version.content).replace("\ufffc", "").strip()
    if not text:
        raise ProviderError("empty_document", "The saved version has no text to check")
    payload = text.encode("utf-8")
    limit = settings.plagiarism_max_text_bytes
    if limit is not None and len(payload) > limit:
        raise ProviderError("text_limit", "The saved version exceeds the configured text limit")
    return payload


async def enqueue(
    session: AsyncSession, version: DocumentVersion, student: User, settings: Settings
) -> PlagiarismCheck:
    if not settings.plagiarism_enabled:
        raise HTTPException(503, "Antiplagiat is disabled")
    try:
        await run_in_threadpool(text_payload, version, settings)
    except ProviderError as exc:
        raise HTTPException(422, str(exc)) from exc
    # Serialize requests for this snapshot. The partial unique index also enforces it.
    await session.execute(
        select(DocumentVersion.id).where(DocumentVersion.id == version.id).with_for_update()
    )
    if await crud.active_check_id(session, version.id) is not None:
        raise HTTPException(409, "This version already has an active check")
    now = await database_now(session)
    check = PlagiarismCheck(
        version_id=version.id,
        requested_by_id=student.id,
        created_at=now,
        updated_at=now,
        next_run_at=now,
    )
    session.add(check)
    await session.commit()
    return check


async def process_due(
    sessions: async_sessionmaker[AsyncSession], settings: Settings, provider: Provider
) -> bool:
    async with sessions() as session:
        claim = await crud.claim_due(
            session,
            await database_now(session),
            2 * settings.plagiarism_request_timeout_seconds + 15,
            settings.plagiarism_check_timeout_seconds,
        )
        if claim is None:
            return False
        check = claim.check
        status, external_id = check.status, check.external_id
        version = (
            await session.get(DocumentVersion, check.version_id)
            if status == CheckStatus.UPLOADING
            else None
        )

    # No database transaction stays open during provider I/O.
    outcome: ProviderStatus | None = None
    failure: ProviderError | None = None
    try:
        if status == CheckStatus.UPLOADING:
            assert version is not None
            payload = await run_in_threadpool(text_payload, version, settings)
            external_id = await run_in_threadpool(
                provider.upload, payload, str(check.requested_by_id)
            )
        elif status == CheckStatus.STARTING:
            assert external_id is not None
            await run_in_threadpool(provider.start, external_id)
        else:
            assert status == CheckStatus.CHECKING and external_id is not None
            outcome = await run_in_threadpool(provider.poll, external_id)
    except ProviderError as exc:
        failure = exc

    async with sessions() as session:
        current = await crud.lock_claim(session, claim)
        if current is None:
            return True
        now = await database_now(session)
        if failure is not None:
            crud.fail(current, now, failure.code, str(failure))
        else:
            current.claim_id = current.claim_until = None
            current.updated_at, current.next_run_at = now, now
            if status == CheckStatus.UPLOADING:
                current.external_id, current.status = external_id, CheckStatus.UPLOADED
            elif status == CheckStatus.STARTING:
                current.status = CheckStatus.CHECKING
            else:
                assert outcome is not None and current.deadline_at is not None
                if outcome.report is not None:
                    current.status = CheckStatus.COMPLETED
                    current.result = outcome.report.model_dump(mode="json")
                    current.finished_at = now
                else:
                    delay = max(
                        settings.plagiarism_poll_seconds, min(outcome.wait_seconds or 0, 300)
                    )
                    current.next_run_at = min(now + timedelta(seconds=delay), current.deadline_at)
        await session.commit()
    return True
