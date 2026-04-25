export type UserTranscriptMessage = {
  type: 'USER_TRANSCRIPT'
  text: string
  sessionId?: string
  turnId?: string
}

export type AIResponseMessage = {
  type: 'AI_RESPONSE'
  responseText: string
  audioUrl?: string
  audioBase64?: string
  audioMimeType?: string
  turnId?: string
}

export type ClientToServerMessage = UserTranscriptMessage

export type ServerToClientMessage = AIResponseMessage
