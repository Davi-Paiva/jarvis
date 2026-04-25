export type SessionStartMessage = {
  type: "SESSION_START";
  sessionId?: string;
  enableAudio?: boolean;  // Set to false to disable audio synthesis and save ElevenLabs credits
};

export type UserTranscriptMessage = {
  type: "USER_TRANSCRIPT";
  text: string;
  sessionId?: string;
  turnId?: string;
  repoAgentId?: string;
};

export type VoiceChatMessage = {
  type: "CHAT_MESSAGE";
  id: string;
  chatId: string;
  repoAgentId: string;
  role: "user" | "assistant" | "system";
  content: string;
  turnId?: string;
  createdAt: string;
};

export type RepoSummary = {
  repoAgentId: string;
  repoId: string;
  displayName: string;
  repoPath: string;
  branchName?: string;
  phase: string;
  status: "idle" | "running" | "waiting_approval";
  activeChatId?: string;
  pendingTurns: number;
};

export type PendingTurnSummary = {
  turnId: string;
  repoAgentId: string;
  repoName: string;
  type: string;
  message: string;
  requiresUserResponse: boolean;
  priority: number;
  createdAt: string;
};

export type SessionStateMessage = {
  type: "SESSION_STATE";
  sessionId: string;
  activeRepoAgentId?: string;
  activeChatId?: string;
  repos: RepoSummary[];
  activeAgent?: RepoSummary;
  pendingTurns: PendingTurnSummary[];
  messages: VoiceChatMessage[];
};

export type AIResponseMessage = {
  type: "AI_RESPONSE";
  responseText: string;
  audioUrl?: string;
  audioBase64?: string;
  audioMimeType?: string;
  turnId?: string;
  repoAgentId?: string;
  chatId?: string;
};

export type AudioStreamStartMessage = {
  type: "AUDIO_STREAM_START";
  turnId: string;
  mimeType: string;
  responseText?: string;
  sampleRate?: number;
  encoding?: string;
};

export type AudioStreamChunkMessage = {
  type: "AUDIO_STREAM_CHUNK";
  turnId: string;
  chunkIndex: number;
  audioBase64: string;
};

export type AudioStreamEndMessage = {
  type: "AUDIO_STREAM_END";
  turnId: string;
  totalChunks: number;
  error?: string;
};

export type PendingTurnMessage = {
  type: "PENDING_TURN";
  pendingTurn: PendingTurnSummary;
};

export type ClientToServerMessage = SessionStartMessage | UserTranscriptMessage;

export type ServerToClientMessage =
  | SessionStateMessage
  | VoiceChatMessage
  | AIResponseMessage
  | PendingTurnMessage
  | AudioStreamStartMessage
  | AudioStreamChunkMessage
  | AudioStreamEndMessage;
