from __future__ import annotations

from typing import Optional

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


__all__ = ["create_orchestrator"]

