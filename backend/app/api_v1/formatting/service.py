from typing import cast
from uuid import UUID

from fastapi import HTTPException
from pydantic import JsonValue
from sqlalchemy.ext.asyncio import AsyncSession

from app.api_v1.formatting.schemas import TemplateCreate, TemplateVersionCreate
from app.core.models import FormattingTemplate, FormattingTemplateVersion


async def create_template(
    session: AsyncSession, supervisor_id: UUID, data: TemplateCreate
) -> tuple[FormattingTemplate, FormattingTemplateVersion]:
    template = FormattingTemplate(supervisor_id=supervisor_id, name=data.name)
    session.add(template)
    await session.flush()
    version = FormattingTemplateVersion(
        template_id=template.id,
        number=1,
        parameters=cast(dict[str, JsonValue], data.parameters.model_dump(mode="json")),
    )
    session.add(version)
    await session.commit()
    return template, version


async def create_version(
    session: AsyncSession, template: FormattingTemplate, data: TemplateVersionCreate
) -> FormattingTemplateVersion:
    if template.latest_version != data.expected_version:
        raise HTTPException(409, "Template version conflict")
    template.latest_version += 1
    version = FormattingTemplateVersion(
        template_id=template.id,
        number=template.latest_version,
        parameters=cast(dict[str, JsonValue], data.parameters.model_dump(mode="json")),
    )
    session.add(version)
    await session.commit()
    return version
