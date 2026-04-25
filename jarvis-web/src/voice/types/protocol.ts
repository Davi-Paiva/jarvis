export type UserTranscriptMessage = {
  type: 'USER_TRANSCRIPT'
  text: string
  sessionId?: string
  turnId?: string
}

// ── Legacy: full audio in one shot ───────────────────────────────────────────
// Kept unchanged; used as fallback when streaming is unavailable.
export type AIResponseMessage = {
  type: 'AI_RESPONSE'
  responseText: string
  audioUrl?: string
  audioBase64?: string
  audioMimeType?: string
  turnId?: string
}

// ── Progressive streaming messages ───────────────────────────────────────────
// Flow for one AI turn:
//   AUDIO_STREAM_START  → N × AUDIO_STREAM_CHUNK  → AUDIO_STREAM_END
//
// Client detects streaming vs full-response by the first message type it sees
// for a given turnId.  AI_RESPONSE still works as the non-streaming fallback.

export type AudioStreamStartMessage = {
  type: 'AUDIO_STREAM_START'
  turnId: string
  mimeType: string        // 'audio/pcm' for PCM streams, 'audio/mpeg' for MP3
  responseText?: string   // available immediately; UI can render text while audio is still coming
  // Present when encoding === 'pcm16le'; absent for MP3 streams.
  sampleRate?: number     // e.g. 22050 — needed to create AudioBuffer
  encoding?: string       // 'pcm16le' | 'mp3'
}

export type AudioStreamChunkMessage = {
  type: 'AUDIO_STREAM_CHUNK'
  turnId: string
  chunkIndex: number      // 0-based, monotonically increasing within a turn
  audioBase64: string     // base64-encoded slice of the raw audio stream
}

export type AudioStreamEndMessage = {
  type: 'AUDIO_STREAM_END'
  turnId: string
  totalChunks: number     // client verifies it received all chunks
  error?: string          // non-null if synthesis failed mid-stream
}

export type ClientToServerMessage = UserTranscriptMessage

export type ServerToClientMessage =
  | AIResponseMessage
  | AudioStreamStartMessage
  | AudioStreamChunkMessage
  | AudioStreamEndMessage

