from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api_v1.documents import service as document_service
from app.api_v1.documents.chapters import chapter_blocks
from app.api_v1.stages import crud, service
from app.api_v1.stages.schemas import (
    StageActionResponse,
    StageDecision,
    StageEventResponse,
    StageSubmit,
)
from app.api_v1.theses.crud import find_accessible_thesis
from app.core.models import (
    Document,
    StageEvent,
    StageStatus,
    StageSubmission,
    Thesis,
    ThesisStage,
    User,
)


async def lock_context(
    session: AsyncSession, stage_id: UUID, user: User, expected_revision: int
) -> tuple[Thesis, ThesisStage, Document]:
    found = await crud.find_accessible_stage(session, stage_id, user)
    if found is None:
        raise HTTPException(404, "Stage not found")
    # All plan/workflow writers lock thesis first, then document. Document writers
    # only lock document and read stage statuses without acquiring a thesis lock.
    thesis = await find_accessible_thesis(session, found.thesis_id, user, lock=True)
    assert thesis is not None
    if thesis.revision != expected_revision:
        raise HTTPException(409, "Thesis revision conflict")
    stages = await crud.list_stages(session, [thesis.id])
    if not stages:
        raise HTTPException(409, "A nonempty stage plan is required")
    stage = next(item for item in stages if item.id == stage_id)
    document = await session.scalar(
        select(Document)
        .where(Document.thesis_id == thesis.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if document is None:
        raise HTTPException(409, "Thesis has no document")
    return thesis, stage, document


async def record_transition(
    session: AsyncSession,
    thesis: Thesis,
    stage: ThesisStage,
    actor_id: UUID,
    before: dict[str, str | int],
    kind: str,
    reason: str | None,
) -> StageActionResponse:
    thesis.revision += 1
    event = StageEvent(
        stage_id=stage.id,
        actor_id=actor_id,
        thesis_revision=thesis.revision,
        kind=kind,
        before=before,
        after=service.stage_snapshot(stage),
        version_id=stage.submitted_version_id,
        reason=reason,
    )
    session.add(event)
    await session.commit()
    return StageActionResponse(
        stage=service.stage_response(stage, datetime.now(UTC).date()),
        revision=thesis.revision,
        event=StageEventResponse.model_validate(event),
    )


async def submit(
    session: AsyncSession, stage_id: UUID, user: User, lease_id: UUID, data: StageSubmit
) -> StageActionResponse:
    thesis, stage, document = await lock_context(session, stage_id, user, data.expected_revision)
    if stage.status not in {StageStatus.IN_PROGRESS, StageStatus.CHANGES_REQUESTED}:
        raise HTTPException(409, "Stage cannot be submitted in its current status")
    await document_service.require_revision_and_lease(
        session, document, user.id, lease_id, data.expected_document_revision
    )
    before = service.stage_snapshot(stage)
    version = await document_service.add_snapshot(session, document, user.id, data.comment)
    session.add(
        StageSubmission(
            stage_id=stage.id,
            version_id=version.id,
            submitted_by_id=user.id,
            thesis_revision=thesis.revision + 1,
            scope="chapter" if stage.id in chapter_blocks(version.content) else "document",
        )
    )
    stage.submitted_version_id = version.id
    stage.status = StageStatus.IN_REVIEW
    return await record_transition(
        session, thesis, stage, user.id, before, "submitted", data.comment
    )


async def decide(
    session: AsyncSession,
    stage_id: UUID,
    user: User,
    data: StageDecision,
    action: Literal["request-changes", "confirm", "resume"],
) -> StageActionResponse:
    thesis, stage, _ = await lock_context(session, stage_id, user, data.expected_revision)
    required = StageStatus.CHANGES_REQUESTED if action == "resume" else StageStatus.IN_REVIEW
    if stage.status != required or stage.submitted_version_id != data.submitted_version_id:
        raise HTTPException(409, "Stage status or submitted version conflict")
    before = service.stage_snapshot(stage)
    kind, stage.status = {
        "request-changes": ("changes_requested", StageStatus.CHANGES_REQUESTED),
        "confirm": ("confirmed", StageStatus.COMPLETED),
        "resume": ("resumed", StageStatus.IN_PROGRESS),
    }[action]
    return await record_transition(session, thesis, stage, user.id, before, kind, data.comment)
