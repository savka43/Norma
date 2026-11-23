from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException

from app.api_v1.auth.dependencies import CurrentUserDep
from app.api_v1.comments import crud
from app.api_v1.dependencies import SessionDep
from app.api_v1.documents import crud as document_crud
from app.core.models import Comment


async def get_comment(comment_id: UUID, user: CurrentUserDep, session: SessionDep) -> Comment:
    comment = await crud.find_comment(session, comment_id)
    if comment is not None:
        version = await document_crud.find_version(session, comment.version_id)
        if version is not None and await document_crud.find_document(
            session, version.document_id, user
        ):
            return comment
    raise HTTPException(404, "Comment not found")


AccessibleCommentDep = Annotated[Comment, Depends(get_comment)]
