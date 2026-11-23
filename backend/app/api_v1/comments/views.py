from typing import Annotated

from fastapi import APIRouter, Query, Response

from app.api_v1.auth.dependencies import CurrentUserDep, SupervisorDep
from app.api_v1.comments import crud, service
from app.api_v1.comments.dependencies import AccessibleCommentDep
from app.api_v1.comments.schemas import (
    CommentCreate,
    CommentEventResponse,
    CommentHistoryPage,
    CommentListParams,
    CommentPage,
    CommentResolve,
    CommentResponse,
)
from app.api_v1.dependencies import SessionDep
from app.api_v1.documents import crud as document_crud
from app.api_v1.documents.dependencies import AccessibleVersionDep
from app.api_v1.documents.structure import semantic_blocks
from app.api_v1.supervisor_groups.schemas import PageParams

router = APIRouter(tags=["comments"])
PageParamsDep = Annotated[PageParams, Query()]


@router.post(
    "/document-versions/{version_id}/comments", status_code=201, responses={403: {}, 404: {}}
)
async def create_comment(
    version: AccessibleVersionDep,
    data: CommentCreate,
    supervisor: SupervisorDep,
    session: SessionDep,
) -> CommentResponse:
    comment = await service.create_comment(session, version, supervisor.id, data)
    return service.comment_response(
        comment,
        await service.current_blocks(session, version.document_id),
        semantic_blocks(version.content),
    )


@router.get("/document-versions/{version_id}/comments", responses={404: {}})
async def list_comments(
    version: AccessibleVersionDep,
    session: SessionDep,
    params: Annotated[CommentListParams, Query()],
    response: Response,
) -> CommentPage:
    items = await service.visible_comments(session, version, params)
    response.headers["Cache-Control"] = "no-store"
    return CommentPage(
        items=items,
        limit=params.limit,
        offset=params.offset,
    )


@router.get("/comments/{comment_id}", responses={404: {}})
async def get_comment(
    comment: AccessibleCommentDep, session: SessionDep, response: Response
) -> CommentResponse:
    version = await document_crud.find_version(session, comment.version_id)
    assert version is not None
    response.headers["Cache-Control"] = "no-store"
    return service.comment_response(
        comment,
        await service.current_blocks(session, version.document_id),
        semantic_blocks(version.content),
    )


@router.patch("/comments/{comment_id}", responses={404: {}, 409: {}})
async def resolve_comment(
    comment: AccessibleCommentDep, data: CommentResolve, user: CurrentUserDep, session: SessionDep
) -> CommentResponse:
    locked = await crud.find_comment(session, comment.id, lock=True)
    assert locked is not None
    await service.resolve_comment(session, locked, user.id, data.expected_revision)
    version = await document_crud.find_version(session, locked.version_id)
    assert version is not None
    return service.comment_response(
        locked,
        await service.current_blocks(session, version.document_id),
        semantic_blocks(version.content),
    )


@router.get("/comments/{comment_id}/history", responses={404: {}})
async def comment_history(
    comment: AccessibleCommentDep, session: SessionDep, params: PageParamsDep, response: Response
) -> CommentHistoryPage:
    items = await crud.list_history(session, comment.id, params)
    response.headers["Cache-Control"] = "no-store"
    return CommentHistoryPage(
        items=[CommentEventResponse.model_validate(item) for item in items],
        limit=params.limit,
        offset=params.offset,
    )
