from threading import BoundedSemaphore
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api_v1.documents import crud as document_crud
from app.api_v1.documents import service as document_service
from app.api_v1.documents.export.docx import ImageAsset, UnsupportedExport, render_docx
from app.api_v1.documents.export.pdf import (
    ConversionFailed,
    ConversionUnavailable,
    font_substitutions,
    render_pdf,
)
from app.api_v1.documents.lexical import LexicalContent, content_nodes
from app.api_v1.formatting.document_schemas import FormattingApply, FormattingIssue
from app.api_v1.formatting.normalize import formatting_issues, normalize
from app.api_v1.formatting.schemas import TemplateParameters
from app.core.config import Settings
from app.core.models import Document, DocumentVersion, FormattingTemplateVersion, Thesis

MAX_EXPORT_BYTES = 32 * 1024 * 1024
EXPORT_SLOTS = BoundedSemaphore(2)


async def version_parameters(session: AsyncSession, version_id: UUID) -> TemplateParameters:
    template = await session.get(FormattingTemplateVersion, version_id)
    assert template is not None
    return TemplateParameters.model_validate(template.parameters)


async def apply_formatting(
    session: AsyncSession, document: Document, actor_id: UUID, lease_id: UUID, data: FormattingApply
) -> tuple[DocumentVersion, DocumentVersion, list[FormattingIssue]]:
    await document_service.require_revision_and_lease(
        session, document, actor_id, lease_id, data.expected_revision
    )
    content = normalize(document.content)
    await document_service.require_editable(session, document, content, data.template_version_id)
    thesis = await session.get(Thesis, document.thesis_id)
    assert thesis is not None
    await document_service.require_template(session, data.template_version_id, thesis.supervisor_id)
    parameters = await version_parameters(session, data.template_version_id)
    issues = formatting_issues(document.content, parameters)
    previous = await document_service.add_snapshot(
        session, document, actor_id, "Before applying formatting template"
    )
    document.content = content
    document.template_version_id = data.template_version_id
    document.revision += 1
    document.updated_at = await document_crud.database_now(session)
    version = await document_service.add_snapshot(
        session, document, actor_id, "Applied formatting template"
    )
    await session.commit()
    return previous, version, issues


async def export_assets(session: AsyncSession, version: DocumentVersion) -> dict[UUID, ImageAsset]:
    assets: dict[UUID, ImageAsset] = {}
    total = 0
    # Count occurrences as well as unique assets to bound rendering work.
    for node in content_nodes(version.content):
        if node["type"] != "norma-image":
            continue
        asset_id = UUID(str(node["asset_id"]))
        if asset_id not in assets:
            asset = await document_crud.find_asset(session, version.document_id, asset_id)
            if asset is None:
                raise HTTPException(422, "An image asset is unavailable")
            assets[asset_id] = ImageAsset(asset.data, asset.width, asset.height)
        total += len(assets[asset_id].data)
        if total > MAX_EXPORT_BYTES:
            raise HTTPException(422, "Export image budget exceeded")
    return assets


def build_export(
    content: LexicalContent,
    parameters: TemplateParameters,
    assets: dict[UUID, ImageAsset],
    output_format: str,
    settings: Settings,
) -> tuple[bytes, list[str]]:
    if not EXPORT_SLOTS.acquire(blocking=False):
        raise HTTPException(503, "Export capacity is busy; retry explicitly later")
    try:
        warnings: list[str] = []
        if formatting_issues(content.stored(), parameters):
            warnings.append("manual_formatting_normalized")
        try:
            data = render_docx(content, parameters, assets)
        except UnsupportedExport as exc:
            raise HTTPException(422, str(exc)) from exc
        if len(data) > MAX_EXPORT_BYTES:
            raise HTTPException(422, "Export output size limit exceeded")
        if output_format == "pdf":
            try:
                if font_substitutions(parameters):
                    warnings.append("font_substitution")
                return render_pdf(
                    data, settings.pdf_converter, settings.pdf_timeout_seconds, MAX_EXPORT_BYTES
                ), warnings
            except ConversionUnavailable as exc:
                raise HTTPException(503, "PDF converter is unavailable") from exc
            except ConversionFailed as exc:
                raise HTTPException(503, "PDF conversion failed or timed out") from exc
        return data, warnings
    finally:
        EXPORT_SLOTS.release()
