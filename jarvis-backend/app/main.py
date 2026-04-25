from __future__ import annotations

from typing import Optional

from fastapi import FastAPI

from app.api.health import router as health_router
from app.api.voice_ws import router as voice_ws_router
from app.config import Settings, load_settings
from app.services.openai_client import LLMClient
from app.services.orchestrator import JarvisOrchestrator


def create_orchestrator(
    settings: Optional[Settings] = None,
    llm_client: Optional[LLMClient] = None,
) -> JarvisOrchestrator:
    """Create the application service container.

    This intentionally does not start FastAPI or register endpoints. Future API
    adapters should depend on this function and call the orchestrator methods.
    """
    return JarvisOrchestrator.create(settings=settings or load_settings(), llm_client=llm_client)


def create_app(
    settings: Optional[Settings] = None,
    llm_client: Optional[LLMClient] = None,
) -> FastAPI:
    resolved_settings = settings or load_settings()
    orchestrator = create_orchestrator(settings=resolved_settings, llm_client=llm_client)

    app = FastAPI(title="Jarvis Backend API")
    app.state.settings = resolved_settings
    app.state.orchestrator = orchestrator
    app.include_router(health_router)
    app.include_router(voice_ws_router)
    return app


__all__ = ["create_orchestrator", "create_app"]

