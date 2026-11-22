from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Response

from app.api_v1.auth.dependencies import CurrentUserDep, SupervisorDep
from app.api_v1.dependencies import SessionDep
from app.api_v1.formatting import crud, service
from app.api_v1.formatting.dependencies import AccessibleTemplateDep, LockedOwnedTemplateDep
from app.api_v1.formatting.presets import gost_parameters
from app.api_v1.formatting.schemas import (
    TemplateCreate,
    TemplateCreatedResponse,
    TemplatePage,
    TemplateParameters,
    TemplateResponse,
    TemplateVersionCreate,
    TemplateVersionPage,
    TemplateVersionResponse,
)
from app.api_v1.supervisor_groups.schemas import PageParams

router = APIRouter(tags=["formatting templates"])
PageParamsDep = Annotated[PageParams, Query()]


@router.get("/formatting-presets/gost-7-32-2017")
async def get_gost_preset(user: CurrentUserDep, response: Response) -> TemplateParameters:
    response.headers["Cache-Control"] = "no-store"
    return gost_parameters()


@router.post("/formatting-templates", status_code=201)
async def create_template(
    data: TemplateCreate, supervisor: SupervisorDep, session: SessionDep
) -> TemplateCreatedResponse:
    template, version = await service.create_template(session, supervisor.id, data)
    return TemplateCreatedResponse(
        template=TemplateResponse.model_validate(template),
        version=TemplateVersionResponse.model_validate(version),
    )


@router.get("/formatting-templates")
async def list_templates(
    user: CurrentUserDep, session: SessionDep, params: PageParamsDep, response: Response
) -> TemplatePage:
    owner_id = await crud.accessible_supervisor_id(session, user)
    templates = await crud.list_templates(session, owner_id, params)
    response.headers["Cache-Control"] = "no-store"
    return TemplatePage(
        items=[TemplateResponse.model_validate(item) for item in templates],
        limit=params.limit,
        offset=params.offset,
    )


@router.get("/formatting-templates/{template_id}/versions", responses={404: {}})
async def list_versions(
    template: AccessibleTemplateDep, session: SessionDep, params: PageParamsDep, response: Response
) -> TemplateVersionPage:
    versions = await crud.list_versions(session, template.id, params)
    response.headers["Cache-Control"] = "no-store"
    return TemplateVersionPage(
        items=[TemplateVersionResponse.model_validate(item) for item in versions],
        limit=params.limit,
        offset=params.offset,
    )


@router.post(
    "/formatting-templates/{template_id}/versions", status_code=201, responses={404: {}, 409: {}}
)
async def create_version(
    data: TemplateVersionCreate, template: LockedOwnedTemplateDep, session: SessionDep
) -> TemplateVersionResponse:
    version = await service.create_version(session, template, data)
    return TemplateVersionResponse.model_validate(version)


@router.get("/formatting-template-versions/{version_id}", responses={404: {}})
async def get_version(
    version_id: UUID, user: CurrentUserDep, session: SessionDep, response: Response
) -> TemplateVersionResponse:
    owner_id = await crud.accessible_supervisor_id(session, user)
    version = await crud.find_version(session, version_id, owner_id)
    if version is None:
        raise HTTPException(404, "Template version not found")
    response.headers["Cache-Control"] = "no-store"
    return TemplateVersionResponse.model_validate(version)
