from __future__ import annotations

import logging

from app.models.schemas import AnalyzeInput, AnalyzeOutput
from app.services.analyze_service import AnalyzeService


logger = logging.getLogger(__name__)


class AnalyzeRequestError(ValueError):
    """Raised when the analyze request payload is incomplete."""


def analyze_file(
    payload: AnalyzeInput,
    service: AnalyzeService | None = None,
) -> AnalyzeOutput:
    file_name = (payload.fileName or "").strip()
    content = (payload.content or "").strip()
    diff = (payload.diff or "").strip()

    if not file_name or not content:
        raise AnalyzeRequestError("fileName and content are required.")

    logger.info("Analyzing %s (%d chars)", file_name, len(content))
    analyzer = service or AnalyzeService()
    return analyzer.analyze(file_name=file_name, content=content, diff=diff)