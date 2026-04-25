"""HTTP transport adapters for the backend."""

from fastapi import APIRouter

from app.api.analyze import router as analyze_router
from app.api.routes import router as folder_router

router = APIRouter()
router.include_router(folder_router)
router.include_router(analyze_router)

__all__ = ["router"]
