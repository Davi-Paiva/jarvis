from __future__ import annotations

from datetime import datetime
from typing import List, Literal, Optional, Union

from pydantic import BaseModel, Field


class SessionStartMessage(BaseModel):
    type: Literal["SESSION_START"]
    sessionId: Optional[str] = None


class UserTranscriptMessage(BaseModel):
    type: Literal["USER_TRANSCRIPT"]
    text: str = Field(min_length=1)
    sessionId: Optional[str] = None
    turnId: Optional[str] = None
    repoAgentId: Optional[str] = None


class VoiceChatMessage(BaseModel):
    type: Literal["CHAT_MESSAGE"] = "CHAT_MESSAGE"
    id: str
    chatId: str
    repoAgentId: str
    role: Literal["user", "assistant", "system"]
    content: str
    turnId: Optional[str] = None
    createdAt: datetime


class RepoSummary(BaseModel):
    repoAgentId: str
    repoId: str
    displayName: str
    repoPath: str
    branchName: Optional[str] = None
    phase: str
    status: Literal["idle", "running", "waiting_approval"]
    activeChatId: Optional[str] = None
    pendingTurns: int = 0


class PendingTurnSummary(BaseModel):
    turnId: str
    repoAgentId: str
    repoName: str
    type: str
    message: str
    requiresUserResponse: bool = False
    priority: int
    createdAt: datetime


class SessionStateMessage(BaseModel):
    type: Literal["SESSION_STATE"] = "SESSION_STATE"
    sessionId: str
    activeRepoAgentId: Optional[str] = None
    activeChatId: Optional[str] = None
    repos: List[RepoSummary] = Field(default_factory=list)
    activeAgent: Optional[RepoSummary] = None
    pendingTurns: List[PendingTurnSummary] = Field(default_factory=list)
    messages: List[VoiceChatMessage] = Field(default_factory=list)


# ── Legacy / fallback full-response message (unchanged) ──────────────────────
class AIResponseMessage(BaseModel):
    type: Literal["AI_RESPONSE"] = "AI_RESPONSE"
    responseText: str
    audioUrl: Optional[str] = None
    audioBase64: Optional[str] = None
    audioMimeType: Optional[str] = "audio/mpeg"
    turnId: Optional[str] = None
<<<<<<< Updated upstream


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
=======
    repoAgentId: Optional[str] = None
    chatId: Optional[str] = None


class PendingTurnMessage(BaseModel):
    type: Literal["PENDING_TURN"] = "PENDING_TURN"
    pendingTurn: PendingTurnSummary


ClientToServerMessage = Union[SessionStartMessage, UserTranscriptMessage]
ServerToClientMessage = Union[
    SessionStateMessage,
    VoiceChatMessage,
    AIResponseMessage,
    PendingTurnMessage,
]
>>>>>>> Stashed changes
