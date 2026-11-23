from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api_v1.dependencies import get_settings
from app.api_v1.plagiarism import crud, service
from app.api_v1.plagiarism.client import ProviderError, ProviderStatus
from app.api_v1.plagiarism.schemas import CheckReport
from app.core.config import Settings
from app.core.models import CheckStatus, PlagiarismCheck
from tests.integration.actors import authenticate
from tests.integration.test_documents import Workspace, acquire, save_payload, snapshot
from tests.integration.test_documents import workspace as workspace

pytestmark = pytest.mark.integration
CONFIRM = {"confirm_demo_document": True}


class FakeProvider:
    def __init__(self, *, reject_start: bool = False) -> None:
        self.uploads: list[tuple[bytes, str]] = []
        self.started: list[int] = []
        self.polled: list[int] = []
        self.reject_start = reject_start

    def upload(self, data: bytes, external_user_id: str) -> int:
        self.uploads.append((data, external_user_id))
        return 42

    def start(self, external_id: int) -> None:
        self.started.append(external_id)
        if self.reject_start:
            raise ProviderError("provider_fault", "Synthetic service rejection")

    def poll(self, external_id: int) -> ProviderStatus:
        self.polled.append(external_id)
        return ProviderStatus(
            report=CheckReport(originality_percent=98, similarity_percent=2, report_number=1)
        )


def sessions(db_session: AsyncSession) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(
        bind=db_session.bind, expire_on_commit=False, join_transaction_mode="create_savepoint"
    )


async def saved_version(client: AsyncClient, workspace: Workspace) -> tuple[str, dict[str, str]]:
    lease = await acquire(client, workspace)
    saved = await client.put(
        f"/api/v1/documents/{workspace.document_id}",
        headers=lease,
        json=save_payload(workspace, 1, "Исходный текст"),
    )
    assert saved.status_code == 200
    version = await snapshot(client, workspace, lease, 2)
    return f"/api/v1/document-versions/{version['id']}/plagiarism-checks", lease


def enable(api_app: FastAPI, settings: Settings) -> Settings:
    enabled = settings.model_copy(update={"plagiarism_enabled": True})
    api_app.dependency_overrides[get_settings] = lambda: enabled
    return enabled


async def test_saved_version_check_survives_separate_worker_sessions_and_is_private(
    api_app: FastAPI,
    api_client: AsyncClient,
    db_session: AsyncSession,
    integration_settings: Settings,
    workspace: Workspace,
) -> None:
    path, lease = await saved_version(api_client, workspace)
    assert (await api_client.post(path, json=CONFIRM)).status_code == 503
    settings = enable(api_app, integration_settings)
    for payload in ({}, {"confirm_demo_document": False}, {"confirm_demo_document": 1}):
        assert (await api_client.post(path, json=payload)).status_code == 422
    check = await api_client.post(path, json=CONFIRM)
    assert check.status_code == 202, check.text
    assert check.json()["status"] == "queued"
    assert (await api_client.post(path, json=CONFIRM)).status_code == 409
    detail = f"/api/v1/plagiarism-checks/{check.json()['id']}"
    assert (await api_client.get(f"{detail}/report")).status_code == 409
    changed = await api_client.put(
        f"/api/v1/documents/{workspace.document_id}",
        headers=lease,
        json=save_payload(workspace, 2, "Несвязанный новый текст"),
    )
    assert changed.status_code == 200

    provider = FakeProvider()
    for status in ("uploaded", "checking", "completed"):
        await db_session.commit()
        assert await service.process_due(sessions(db_session), settings, provider)
        current = await api_client.get(detail)
        assert current.status_code == 200
        assert current.headers["cache-control"] == "no-store"
        assert current.json()["status"] == status and current.json()["external_id"] == 42
    assert provider.uploads == [("Исходный текст".encode(), str(workspace.actors.student.id))]
    assert provider.started == provider.polled == [42]

    authenticate(api_client, workspace.actors, workspace.actors.owner)
    report = await api_client.get(f"{detail}/report")
    assert report.status_code == 200 and report.json()["originality_percent"] == 98
    assert (await api_client.post(path, json=CONFIRM)).status_code == 403
    for user in (workspace.actors.peer, workspace.actors.other):
        authenticate(api_client, workspace.actors, user)
        assert (await api_client.get(path)).status_code == 404
        assert (await api_client.get(detail)).status_code == 404
        assert (await api_client.get(f"{detail}/report")).status_code == 404
    with pytest.raises(IntegrityError, match="Finished plagiarism checks are immutable"):
        async with db_session.begin_nested():
            await db_session.execute(
                update(PlagiarismCheck)
                .where(PlagiarismCheck.id == UUID(check.json()["id"]))
                .values(result={"originality_percent": 1})
            )


async def test_failed_external_call_requires_new_user_request(
    api_app: FastAPI,
    api_client: AsyncClient,
    db_session: AsyncSession,
    integration_settings: Settings,
    workspace: Workspace,
) -> None:
    settings = enable(api_app, integration_settings)
    path, _ = await saved_version(api_client, workspace)
    attempt = await api_client.post(path, json=CONFIRM)
    assert attempt.status_code == 202
    provider = FakeProvider(reject_start=True)
    worker_sessions = sessions(db_session)
    assert await service.process_due(worker_sessions, settings, provider)
    assert await service.process_due(worker_sessions, settings, provider)
    assert not await service.process_due(worker_sessions, settings, provider)
    history = f"/api/v1/plagiarism-checks/{attempt.json()['id']}"
    failed = (await api_client.get(history)).json()
    assert failed["status"] == "failed" and failed["external_id"] == 42
    assert failed["error_detail"] == "Synthetic service rejection"
    assert len(provider.uploads) == 1 and provider.started == [42] and not provider.polled
    retry = await api_client.post(path, json=CONFIRM)
    assert retry.status_code == 202 and retry.json()["id"] != failed["id"]
    history_response = await api_client.get(path)
    assert [item["status"] for item in history_response.json()["items"]] == ["queued", "failed"]


@pytest.mark.parametrize(
    "interrupted", [CheckStatus.UPLOADING, CheckStatus.STARTING, CheckStatus.CHECKING]
)
async def test_worker_recovers_expired_claims_without_repeating_mutations(
    interrupted: CheckStatus,
    api_app: FastAPI,
    api_client: AsyncClient,
    db_session: AsyncSession,
    integration_settings: Settings,
    workspace: Workspace,
) -> None:
    settings = enable(api_app, integration_settings)
    path, _ = await saved_version(api_client, workspace)
    attempt = await api_client.post(path, json=CONFIRM)
    assert attempt.status_code == 202
    now = datetime.now(UTC)
    provider = FakeProvider()
    worker_sessions = sessions(db_session)
    if interrupted in {CheckStatus.STARTING, CheckStatus.CHECKING}:
        assert await service.process_due(worker_sessions, settings, provider)
    if interrupted == CheckStatus.CHECKING:
        assert await service.process_due(worker_sessions, settings, provider)
    async with worker_sessions() as worker:
        claim = await crud.claim_due(worker, now + timedelta(seconds=1), 30, 100)
        assert claim is not None and claim.check.status == interrupted
        # A different worker cannot claim the same active operation.
        assert await crud.claim_due(worker, now + timedelta(seconds=2), 30, 100) is None
        await worker.execute(
            update(PlagiarismCheck)
            .where(PlagiarismCheck.id == claim.check.id)
            .values(claim_until=now - timedelta(seconds=1))
        )
        await worker.commit()
    after_restart = FakeProvider()
    await service.process_due(worker_sessions, settings, after_restart)
    latest = await api_client.get(f"/api/v1/plagiarism-checks/{attempt.json()['id']}")
    assert not after_restart.uploads and not after_restart.started
    if interrupted == CheckStatus.CHECKING:
        assert after_restart.polled == [42] and latest.json()["status"] == "completed"
    else:
        assert not after_restart.polled and latest.json()["error_code"] == "interrupted"
    async with worker_sessions() as worker:
        assert await crud.lock_claim(worker, claim) is None
