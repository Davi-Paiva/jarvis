from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request, status

from app.controllers.analyze_controller import AnalyzeRequestError, analyze_file
from app.models.schemas import AnalyzeInput, AnalyzeOutput
from app.services.analyze_service import AnalyzeService


logger = logging.getLogger(__name__)
router = APIRouter()


@router.post(
    "/analyze",
    response_model=AnalyzeOutput,
    status_code=status.HTTP_200_OK,
)
async def analyze(payload: AnalyzeInput, request: Request) -> AnalyzeOutput:
    logger.info("Received analyze request for %s", payload.fileName or "<missing>")
    orchestrator = getattr(request.app.state, "orchestrator", None)
    llm_client = getattr(orchestrator, "llm_client", None)
    try:
        return await analyze_file(payload, service=AnalyzeService(llm_client=llm_client))
    except AnalyzeRequestError as exc:
        logger.warning("Invalid analyze request: %s", exc)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:  # pragma: no cover - defensive guard
        logger.exception("Analyze request failed unexpectedly")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to analyze file.",
        ) from exc