from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


class UserTranscriptMessage(BaseModel):
    type: Literal["USER_TRANSCRIPT"]
    text: str = Field(min_length=1)
    sessionId: Optional[str] = None
    turnId: Optional[str] = None


# ── Legacy / fallback full-response message (unchanged) ──────────────────────
class AIResponseMessage(BaseModel):
    type: Literal["AI_RESPONSE"] = "AI_RESPONSE"
    responseText: str
    audioUrl: Optional[str] = None
    audioBase64: Optional[str] = None
    audioMimeType: Optional[str] = "audio/mpeg"
    turnId: Optional[str] = None


# ── Progressive streaming messages ───────────────────────────────────────────
# Flow: AUDIO_STREAM_START → N × AUDIO_STREAM_CHUNK → AUDIO_STREAM_END
# The client detects streaming by seeing AUDIO_STREAM_START arrive first for a
# given turnId. AI_RESPONSE still works as the non-streaming fallback path.

class AudioStreamStartMessage(BaseModel):
    """Sent once before the first chunk.  Carries the text so the UI can
    render the response immediately while audio is still being received.
    sampleRate and encoding are set when the backend uses PCM output.
    """
    type: Literal["AUDIO_STREAM_START"] = "AUDIO_STREAM_START"
    turnId: str
    mimeType: str = "audio/mpeg"
    responseText: Optional[str] = None
    # PCM metadata — present when encoding == 'pcm16le', absent for MP3
    sampleRate: Optional[int] = None   # e.g. 22050
    encoding: Optional[str] = None     # 'pcm16le' | 'mp3'


class AudioStreamChunkMessage(BaseModel):
    """One slice of the ElevenLabs audio stream, base64-encoded.
    chunkIndex is 0-based and monotonically increasing within a turn."""
    type: Literal["AUDIO_STREAM_CHUNK"] = "AUDIO_STREAM_CHUNK"
    turnId: str
    chunkIndex: int
    audioBase64: str


class AudioStreamEndMessage(BaseModel):
    """Sent once after the last chunk (or on error).
    totalChunks lets the client verify it received everything.
    error is non-None if synthesis failed mid-stream."""
    type: Literal["AUDIO_STREAM_END"] = "AUDIO_STREAM_END"
    turnId: str
    totalChunks: int
    error: Optional[str] = None
