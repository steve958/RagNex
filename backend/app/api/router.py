from __future__ import annotations

from fastapi import APIRouter

from backend.app.api.v1.auth import router as auth_router
from backend.app.api.v1.api_keys import router as api_keys_router
from backend.app.api.v1.tenants import router as tenants_router
from backend.app.api.v1.tasks import router as tasks_router
from backend.app.api.v1.documents import router as documents_router
from backend.app.api.v1.chunks import router as chunks_router
from backend.app.api.v1.knowledgebases import router as knowledgebases_router

api_router = APIRouter()
api_router.include_router(auth_router, prefix="/auth", tags=["auth"])
api_router.include_router(api_keys_router, tags=["api-keys"])
api_router.include_router(tenants_router, tags=["tenants"])
api_router.include_router(tasks_router, tags=["tasks"])
api_router.include_router(documents_router, tags=["documents"])
api_router.include_router(chunks_router, tags=["chunks"])
api_router.include_router(knowledgebases_router, tags=["knowledgebases"])
