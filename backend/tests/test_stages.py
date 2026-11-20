from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

import pytest

from app.api_v1.stages.service import stage_response, thesis_response
from app.core.models import StageStatus, Thesis, ThesisStage


@pytest.mark.parametrize(
    ("statuses", "percent"),
    [
        ([], None),
        ([StageStatus.IN_PROGRESS, StageStatus.IN_REVIEW, StageStatus.CHANGES_REQUESTED], 0),
        ([StageStatus.COMPLETED] * 3, 100),
        ([StageStatus.COMPLETED, StageStatus.IN_PROGRESS, StageStatus.IN_REVIEW], 100 / 3),
    ],
)
def test_progress_counts_all_required_stages(
    statuses: list[StageStatus], percent: float | None
) -> None:
    today = date(2026, 11, 20)
    thesis = Thesis(
        id=uuid4(),
        student_id=uuid4(),
        supervisor_id=uuid4(),
        title="ВКР",
        revision=1,
        start_date=today - timedelta(days=100),
        due_date=today - timedelta(days=1),
        created_at=datetime.now(UTC),
    )
    stages = [
        ThesisStage(
            id=uuid4(),
            thesis_id=thesis.id,
            name=f"Этап {index}",
            position=index,
            due_date=today - timedelta(days=1),
            status=status,
            created_at=datetime.now(UTC),
        )
        for index, status in enumerate(statuses, start=1)
    ]
    response = thesis_response(thesis, stages, today)
    if percent is None:
        assert response.progress_percent is None
    else:
        assert response.progress_percent == pytest.approx(percent)
    assert response.total_stages == len(statuses)
    assert response.is_overdue == (not statuses or percent != 100)


@pytest.mark.parametrize("status", list(StageStatus))
@pytest.mark.parametrize("days_until_due", [-1, 0, 1])
def test_deadline_boundary_and_completed_exemption(
    status: StageStatus, days_until_due: int
) -> None:
    today = date(2026, 11, 20)
    stage = ThesisStage(
        id=uuid4(),
        thesis_id=uuid4(),
        name="Этап",
        position=1,
        due_date=today + timedelta(days=days_until_due),
        status=status,
        created_at=datetime.now(UTC),
    )
    assert stage_response(stage, today).is_overdue == (
        days_until_due < 0 and status != StageStatus.COMPLETED
    )
