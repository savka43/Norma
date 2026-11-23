from datetime import date
from uuid import UUID, uuid4

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api_v1.stages import crud
from app.api_v1.stages.schemas import StageResponse, StageWrite
from app.api_v1.theses.schemas import ThesisResponse
from app.core.models import StageEvent, StageStatus, Thesis, ThesisStage


def stage_snapshot(stage: ThesisStage) -> dict[str, str | int]:
    result: dict[str, str | int] = {
        "name": stage.name,
        "position": stage.position,
        "due_date": stage.due_date.isoformat(),
        "status": stage.status.value,
    }
    if stage.submitted_version_id is not None:
        result["submitted_version_id"] = str(stage.submitted_version_id)
    return result


def stage_response(stage: ThesisStage, as_of: date) -> StageResponse:
    return StageResponse(
        id=stage.id,
        thesis_id=stage.thesis_id,
        name=stage.name,
        position=stage.position,
        due_date=stage.due_date,
        status=stage.status,
        created_at=stage.created_at,
        is_overdue=stage.due_date < as_of and stage.status != StageStatus.COMPLETED,
        submitted_version_id=stage.submitted_version_id,
    )


def thesis_response(thesis: Thesis, stages: list[ThesisStage], as_of: date) -> ThesisResponse:
    total = len(stages)
    completed = sum(stage.status == StageStatus.COMPLETED for stage in stages)
    return ThesisResponse(
        id=thesis.id,
        student_id=thesis.student_id,
        supervisor_id=thesis.supervisor_id,
        title=thesis.title,
        start_date=thesis.start_date,
        due_date=thesis.due_date,
        revision=thesis.revision,
        created_at=thesis.created_at,
        total_stages=total,
        completed_stages=completed,
        progress_percent=100 * completed / total if total else None,
        overdue_stages=sum(
            stage.due_date < as_of and stage.status != StageStatus.COMPLETED for stage in stages
        ),
        is_overdue=thesis.due_date < as_of and (total == 0 or completed != total),
        as_of_date=as_of,
    )


async def write_stage(
    session: AsyncSession,
    thesis: Thesis,
    actor_id: UUID,
    data: StageWrite,
    *,
    stage_id: UUID | None = None,
) -> list[ThesisStage]:
    # Every plan writer must first lock the parent thesis, then read its stages.
    if thesis.revision != data.expected_revision:
        raise HTTPException(status.HTTP_409_CONFLICT, "Thesis revision conflict")
    stages = await crud.list_stages(session, [thesis.id])
    if any(stage.status in {StageStatus.IN_REVIEW, StageStatus.COMPLETED} for stage in stages):
        raise HTTPException(status.HTTP_409_CONFLICT, "Stage plan is locked during or after review")
    if not thesis.start_date <= data.due_date <= thesis.due_date:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "Stage deadline outside thesis dates"
        )
    existing = next((stage for stage in stages if stage.id == stage_id), None)
    if stage_id is not None and existing is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Stage not found")
    max_position = len(stages) + (1 if stage_id is None else 0)
    if data.position > max_position:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Stage position outside plan")
    before = {stage.id: stage_snapshot(stage) for stage in stages}
    if existing is None:
        existing = ThesisStage(
            id=uuid4(),
            thesis_id=thesis.id,
            name=data.name,
            due_date=data.due_date,
            position=data.position,
            status=StageStatus.IN_PROGRESS,
        )
        session.add(existing)
    else:
        stages.remove(existing)
        existing.name = data.name
        existing.due_date = data.due_date
    stages.insert(data.position - 1, existing)
    for position, stage in enumerate(stages, start=1):
        stage.position = position
    changed = [stage for stage in stages if before.get(stage.id) != stage_snapshot(stage)]
    if changed:
        thesis.revision += 1
        # Flush the stages first: FK insertion order must not depend on ORM relationships.
        await session.flush()
        for stage in changed:
            session.add(
                StageEvent(
                    stage_id=stage.id,
                    actor_id=actor_id,
                    thesis_revision=thesis.revision,
                    kind="created" if stage.id not in before else "updated",
                    before=before.get(stage.id),
                    after=stage_snapshot(stage),
                )
            )
    await session.commit()
    return stages
