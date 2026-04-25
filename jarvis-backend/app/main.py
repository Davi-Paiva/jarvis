from __future__ import annotations

from typing import Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import router as api_router

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
    app = FastAPI(title="Jarvis Backend", version="0.1.0")
    
    # Add CORS middleware to allow requests from Tauri frontend
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:1420",  # Vite dev server
            "tauri://localhost",      # Tauri protocol
            "https://tauri.localhost", # Tauri HTTPS
        ],
        allow_credentials=True,
        allow_methods=["*"],  # Allow all HTTP methods including OPTIONS
        allow_headers=["*"],  # Allow all headers
    )
    
    app.state.orchestrator = create_orchestrator(settings=settings, llm_client=llm_client)
    app.include_router(api_router)
    return app


app = create_app()


__all__ = ["app", "create_app", "create_orchestrator"]
