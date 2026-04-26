from __future__ import annotations

import logging

from app.models.schemas import AnalyzeInput, AnalyzeOutput
from app.services.analyze_service import AnalyzeService


logger = logging.getLogger(__name__)


class AnalyzeRequestError(ValueError):
    """Raised when the analyze request payload is incomplete."""


async def analyze_file(
    payload: AnalyzeInput,
    service: AnalyzeService | None = None,
) -> AnalyzeOutput:
    file_name = (payload.fileName or "").strip()
    content = (payload.content or "").strip()
    diff = (payload.diff or "").strip()

    if not file_name or not content:
        raise AnalyzeRequestError("fileName and content are required.")

    logger.info("Analyzing %s (%d chars)", file_name, len(content))
    logger.info(
        "Received git diff for %s:\n--- BEGIN GIT DIFF ---\n%s\n--- END GIT DIFF ---",
        file_name,
        diff or "<empty diff>",
    )
    analyzer = service or AnalyzeService()
    return await analyzer.analyze(file_name=file_name, content=content, diff=diff)