import asyncio
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.api_v1.documents.docx_import import DOCX_MEDIA_TYPE
from app.core.config import Settings
from app.core.database import create_engine, create_session_factory
from app.core.models import (
    Comment,
    CommentEvent,
    Document,
    DocumentAsset,
    DocumentEditLease,
    DocumentImport,
    DocumentVersion,
    FormattingTemplate,
    FormattingTemplateVersion,
    GroupMembership,
    StageEvent,
    StageSubmission,
    SupervisorGroup,
    Thesis,
    ThesisStage,
    User,
)
from app.main import create_app
from tests.document_helpers import content, parameters
from tests.docx_helpers import docx, paragraph
from tests.integration.actors import authenticate, make_actors, seed_actors
from tests.integration.alembic_helpers import run_alembic

pytestmark = pytest.mark.integration


@pytest.mark.parametrize(
    "operation", ["submit", "save", "import", "restore", "format", "decision", "resolve"]
)
def test_review_races_have_one_winner_and_preserve_history(
    migrated_database: None,
    integration_settings: Settings,
    operation: str,
) -> None:
    actors = make_actors()

    async def prepare_or_cleanup(*, cleanup: bool) -> None:
        engine = create_engine(integration_settings)
        try:
            async with create_session_factory(engine)() as session:
                if not cleanup:
                    await seed_actors(session, actors)
                    return
                thesis_ids = select(Thesis.id).where(Thesis.student_id == actors.student.id)
                documents = select(Document.id).where(Document.thesis_id.in_(thesis_ids))
                versions = select(DocumentVersion.id).where(
                    DocumentVersion.document_id.in_(documents)
                )
                stages = select(ThesisStage.id).where(ThesisStage.thesis_id.in_(thesis_ids))
                comments = select(Comment.id).where(Comment.version_id.in_(versions))
                await session.execute(
                    delete(CommentEvent).where(CommentEvent.comment_id.in_(comments))
                )
                await session.execute(delete(Comment).where(Comment.id.in_(comments)))
                await session.execute(delete(StageEvent).where(StageEvent.stage_id.in_(stages)))
                await session.execute(
                    delete(StageSubmission).where(StageSubmission.stage_id.in_(stages))
                )
                await session.execute(delete(ThesisStage).where(ThesisStage.id.in_(stages)))
                await session.execute(
                    delete(DocumentAsset).where(DocumentAsset.document_id.in_(documents))
                )
                await session.execute(
                    delete(DocumentImport).where(DocumentImport.document_id.in_(documents))
                )
                await session.execute(
                    delete(DocumentEditLease).where(DocumentEditLease.document_id.in_(documents))
                )
                await session.execute(
                    delete(DocumentVersion).where(
                        DocumentVersion.id.in_(versions),
                        DocumentVersion.restored_from_id.is_not(None),
                    )
                )
                await session.execute(
                    delete(DocumentVersion).where(DocumentVersion.id.in_(versions))
                )
                await session.execute(delete(Document).where(Document.id.in_(documents)))
                await session.execute(delete(Thesis).where(Thesis.id.in_(thesis_ids)))
                templates = select(FormattingTemplate.id).where(
                    FormattingTemplate.supervisor_id == actors.owner.id
                )
                await session.execute(
                    delete(FormattingTemplateVersion).where(
                        FormattingTemplateVersion.template_id.in_(templates)
                    )
                )
                await session.execute(
                    delete(FormattingTemplate).where(FormattingTemplate.id.in_(templates))
                )
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

    asyncio.run(prepare_or_cleanup(cleanup=False))
    try:
        with (
            TestClient(
                create_app(integration_settings), headers={"X-CSRF-Protection": "1"}
            ) as first,
            TestClient(
                create_app(integration_settings), headers={"X-CSRF-Protection": "1"}
            ) as second,
        ):
            authenticate(first, actors, actors.owner)
            template = first.post(
                "/api/v1/formatting-templates", json={"name": "Гонка", "parameters": parameters()}
            )
            assert template.status_code == 201, template.text
            template_id = template.json()["version"]["id"]
            thesis = first.post(
                "/api/v1/theses",
                json={
                    "student_id": str(actors.student.id),
                    "title": "Гонка",
                    "start_date": "2026-01-01",
                    "due_date": "2027-06-30",
                },
            )
            assert thesis.status_code == 201, thesis.text
            thesis_id = thesis.json()["id"]
            created = first.post(
                f"/api/v1/theses/{thesis_id}/stages",
                json={
                    "name": "Глава",
                    "position": 1,
                    "due_date": "2027-05-01",
                    "expected_revision": 1,
                },
            )
            assert created.status_code == 201, created.text
            stage_id = created.json()["items"][0]["id"]
            authenticate(first, actors, actors.student)
            created_doc = first.post(
                f"/api/v1/theses/{thesis_id}/document", json={"template_version_id": template_id}
            )
            assert created_doc.status_code == 201, created_doc.text
            base = f"/api/v1/documents/{created_doc.json()['id']}"
            lease_response = first.post(f"{base}/edit-lease")
            assert lease_response.status_code == 201
            lease = {"X-Edit-Lease": lease_response.json()["lease_id"]}
            stage_path = f"/api/v1/stages/{stage_id}"
            version_id, comment_id = "", ""
            document_revision = 1
            if operation == "resolve":
                saved = first.put(
                    base,
                    headers=lease,
                    json={
                        "expected_revision": 1,
                        "schema_version": 1,
                        "template_version_id": template_id,
                        "content": content("Цитата"),
                    },
                )
                assert saved.status_code == 200
                document_revision = 2
            if operation in {"restore", "resolve"}:
                version_response = first.post(
                    f"{base}/versions", headers=lease, json={"expected_revision": document_revision}
                )
                assert version_response.status_code == 201
                version_id = version_response.json()["id"]
            if operation == "decision":
                submitted = first.post(
                    f"{stage_path}/submit",
                    headers=lease,
                    json={"expected_revision": 2, "expected_document_revision": 1},
                )
                assert submitted.status_code == 201
                version_id = submitted.json()["stage"]["submitted_version_id"]
            if operation == "resolve":
                authenticate(first, actors, actors.owner)
                comment_response = first.post(
                    f"/api/v1/document-versions/{version_id}/comments",
                    json={
                        "body": "Исправить",
                        "quote": "Цитата",
                        "anchor": {"block_id": "0", "offset_start": 0, "offset_end": 6},
                    },
                )
                assert comment_response.status_code == 201
                comment_id = comment_response.json()["id"]
            for client in (first, second):
                authenticate(
                    client, actors, actors.owner if operation == "decision" else actors.student
                )
            barrier = Barrier(2)

            def write(client: TestClient, index: int) -> int:
                barrier.wait(timeout=10)
                if operation == "decision":
                    action = "confirm" if index == 0 else "request-changes"
                    return client.post(
                        f"{stage_path}/{action}",
                        json={"expected_revision": 3, "submitted_version_id": version_id},
                    ).status_code
                if operation == "resolve":
                    return client.patch(
                        f"/api/v1/comments/{comment_id}",
                        json={"status": "resolved", "expected_revision": 1},
                    ).status_code
                if index == 0 or operation == "submit":
                    return client.post(
                        f"{stage_path}/submit",
                        headers=lease,
                        json={"expected_revision": 2, "expected_document_revision": 1},
                    ).status_code
                if operation == "save":
                    return client.put(
                        base,
                        headers=lease,
                        json={
                            "expected_revision": 1,
                            "schema_version": 1,
                            "template_version_id": template_id,
                            "content": content("Победитель сохранения"),
                        },
                    ).status_code
                if operation == "import":
                    return client.post(
                        f"{base}/import",
                        headers={**lease, "Content-Type": DOCX_MEDIA_TYPE},
                        params={"expected_revision": 1, "confirm_replace": "true"},
                        content=docx(paragraph("Победитель импорта")),
                    ).status_code
                if operation == "format":
                    return client.post(
                        f"{base}/apply-formatting",
                        headers=lease,
                        json={
                            "expected_revision": 1,
                            "template_version_id": template_id,
                            "confirm_apply": True,
                        },
                    ).status_code
                assert operation == "restore"
                return client.post(
                    f"{base}/restore",
                    headers=lease,
                    json={"expected_revision": 1, "version_id": version_id},
                ).status_code

            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = [pool.submit(write, first, 0), pool.submit(write, second, 1)]
                statuses = [future.result(timeout=30) for future in futures]
            assert statuses.count(409) == 1, statuses
            assert sum(status in {200, 201} for status in statuses) == 1, statuses
            if operation == "resolve":
                history = first.get(f"/api/v1/comments/{comment_id}/history").json()["items"]
                assert [item["status"] for item in history] == ["open", "resolved"]
                assert first.get(f"/api/v1/theses/{thesis_id}").json()["revision"] == 2
                return
            submissions = first.get(f"{stage_path}/submissions").json()["items"]
            events = first.get(f"{stage_path}/history").json()["items"]
            if operation == "decision":
                assert len(submissions) == 1 and len(events) == 3
                assert first.get(f"/api/v1/theses/{thesis_id}").json()["revision"] == 4
                with pytest.raises(
                    AssertionError, match="Cannot downgrade while review history exists"
                ):
                    run_alembic(integration_settings, "downgrade", "0008_semantic_captions")
                assert first.get(f"{stage_path}/history").json()["items"] == events
                return
            won_submit = statuses[0] == 201 or operation == "submit"
            assert len(submissions) == (1 if won_submit else 0)
            assert len(events) == (2 if won_submit else 1)
            document = first.get(base).json()
            assert document["revision"] == (1 if won_submit else 2)
            if won_submit:
                pinned = first.get(
                    f"/api/v1/document-versions/{submissions[0]['version_id']}"
                ).json()
                assert pinned["content"] == document["content"]
            versions = first.get(f"{base}/versions").json()["items"]
            expected_versions = (1 if operation == "restore" else 0) + (
                1 if won_submit or operation in {"save", "restore"} else 2
            )
            if operation == "save" and not won_submit:
                expected_versions = 0
            assert len(versions) == expected_versions
    finally:
        asyncio.run(prepare_or_cleanup(cleanup=True))
