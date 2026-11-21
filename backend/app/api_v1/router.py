from fastapi import APIRouter

from app.api_v1.auth.views import router as auth_router
from app.api_v1.documents.import_views import router as document_import_router
from app.api_v1.documents.views import router as documents_router
from app.api_v1.formatting.views import router as formatting_router
from app.api_v1.health.views import router as health_router
from app.api_v1.stages.views import router as stages_router
from app.api_v1.supervisor_groups.views import router as groups_router
from app.api_v1.theses.views import router as theses_router
from app.api_v1.users.views import router as users_router

router = APIRouter(prefix="/api/v1")
router.include_router(health_router)
router.include_router(auth_router)
router.include_router(groups_router)
router.include_router(users_router)
router.include_router(theses_router)
router.include_router(stages_router)
router.include_router(formatting_router)
router.include_router(documents_router)
router.include_router(document_import_router)
