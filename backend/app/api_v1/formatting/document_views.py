from fastapi import APIRouter, Response
from starlette.concurrency import run_in_threadpool

from app.api_v1.dependencies import SessionDep, SettingsDep
from app.api_v1.documents.dependencies import (
    AccessibleVersionDep,
    LeaseIdDep,
    LockedOwnedDocumentDep,
    StudentDep,
)
from app.api_v1.documents.export.docx import DOCX_MEDIA_TYPE
from app.api_v1.documents.lexical import LexicalContent
from app.api_v1.documents.schemas import DocumentResponse, VersionResponse
from app.api_v1.formatting import document_service
from app.api_v1.formatting.document_schemas import (
    ExportRequest,
    FormattingApplied,
    FormattingApply,
    FormattingReport,
)
from app.api_v1.formatting.normalize import MAX_REPORTED_ISSUES, formatting_issues

router = APIRouter(tags=["document formatting and export"])


@router.post("/document-versions/{version_id}/format-check", responses={404: {}})
async def check_formatting(
    version: AccessibleVersionDep, session: SessionDep, response: Response
) -> FormattingReport:
    parameters = await document_service.version_parameters(session, version.template_version_id)
    issues = await run_in_threadpool(formatting_issues, version.content, parameters)
    response.headers["Cache-Control"] = "no-store"
    return FormattingReport(
        version_id=version.id,
        template_version_id=version.template_version_id,
        parameters=parameters,
        conforms=not issues,
        issue_count=len(issues),
        issues=issues[:MAX_REPORTED_ISSUES],
        truncated=len(issues) > MAX_REPORTED_ISSUES,
    )


@router.post(
    "/documents/{document_id}/apply-formatting",
    responses={403: {}, 404: {}, 409: {}},
    response_model_exclude_unset=True,
)
async def apply_formatting(
    data: FormattingApply,
    document: LockedOwnedDocumentDep,
    student: StudentDep,
    lease_id: LeaseIdDep,
    session: SessionDep,
    response: Response,
) -> FormattingApplied:
    previous, version, issues = await document_service.apply_formatting(
        session, document, student.id, lease_id, data
    )
    response.headers["Cache-Control"] = "no-store"
    return FormattingApplied(
        document=DocumentResponse.model_validate(document),
        previous_version=VersionResponse.model_validate(previous),
        version=VersionResponse.model_validate(version),
        corrected_issues=len(issues),
    )


@router.post(
    "/document-versions/{version_id}/exports",
    response_class=Response,
    responses={
        200: {
            "content": {
                DOCX_MEDIA_TYPE: {"schema": {"type": "string", "format": "binary"}},
                "application/pdf": {"schema": {"type": "string", "format": "binary"}},
            }
        },
        404: {},
        422: {},
        503: {},
    },
)
async def export_version(
    data: ExportRequest, version: AccessibleVersionDep, session: SessionDep, settings: SettingsDep
) -> Response:
    parameters = await document_service.version_parameters(session, version.template_version_id)
    assets = await document_service.export_assets(session, version)
    content = LexicalContent.model_validate(version.content)
    version_id, template_version_id = version.id, version.template_version_id
    # Release the read transaction before slow CPU work / subprocess conversion.
    await session.commit()
    output, warnings = await run_in_threadpool(
        document_service.build_export, content, parameters, assets, data.format, settings
    )
    return Response(
        output,
        media_type=DOCX_MEDIA_TYPE if data.format == "docx" else "application/pdf",
        headers={
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
            "Content-Disposition": f'attachment; filename="{version_id}.{data.format}"',
            "X-Document-Version": str(version_id),
            "X-Template-Version": str(template_version_id),
            "X-Export-Warnings": ",".join(warnings),
        },
    )
