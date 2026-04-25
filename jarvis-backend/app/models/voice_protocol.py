from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


class UserTranscriptMessage(BaseModel):
    type: Literal["USER_TRANSCRIPT"]
    text: str = Field(min_length=1)
    sessionId: Optional[str] = None
    turnId: Optional[str] = None


class AIResponseMessage(BaseModel):
    type: Literal["AI_RESPONSE"] = "AI_RESPONSE"
    responseText: str
    audioUrl: Optional[str] = None
    audioBase64: Optional[str] = None
    audioMimeType: Optional[str] = "audio/mpeg"
    turnId: Optional[str] = None
