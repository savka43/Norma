from fastapi import APIRouter

from app.api_v1.health.views import router as health_router

router = APIRouter(prefix="/api/v1")
router.include_router(health_router)
