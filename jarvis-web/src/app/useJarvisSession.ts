import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useVoice } from '../voice/context/VoiceProvider';
import type { Message, ApprovalRequest, Agent } from '../shared/types';
import type {
  PendingTurnMessage,
  PendingTurnSummary,
  RepoSummary,
  ServerToClientMessage,
  SessionStateMessage,
  VoiceChatMessage,
} from '../voice/types/protocol';

const EMPTY_AGENT: Agent = {
  id: 'no-repo',
  name: 'No repository selected',
  status: 'idle',
};

export function useJarvisSession() {
  const voice = useVoice();

  const [connectionState, setConnectionState] = useState<
    'disconnected' | 'connecting' | 'connected'
  >('disconnected');
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [activeRepoAgentId, setActiveRepoAgentId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [pendingTurns, setPendingTurns] = useState<PendingTurnSummary[]>([]);
  const [activeAgentSummary, setActiveAgentSummary] = useState<RepoSummary | null>(null);
  const connectRequestedRef = useRef(false);

  useEffect(() => {
    return voice.addServerMessageListener((message) => {
      handleServerMessage(
        message,
        setSessionId,
        setConnectionState,
        setActiveRepoAgentId,
        setMessages,
        setPendingTurns,
        setActiveAgentSummary,
      );
    });
  }, [voice]);

  useEffect(() => {
    if (!voice.socketConnected) {
      if (connectionState === 'connected') {
        setConnectionState('disconnected');
      }
      return;
    }

    if (connectRequestedRef.current && connectionState !== 'connected') {
      const sent = voice.sendClientMessage({
        type: 'SESSION_START',
        sessionId: sessionId ?? undefined,
        enableAudio: true,  // Web app uses audio playback
      });
      if (sent) {
        setConnectionState('connecting');
      }
    }
  }, [connectionState, sessionId, voice]);

  useEffect(() => {
    const activePendingTurn = pendingTurns.find(
      (turn) =>
        turn.repoAgentId === activeRepoAgentId && turn.requiresUserResponse,
    );
    voice.setTranscriptContext({
      sessionId: sessionId ?? undefined,
      repoAgentId: activeRepoAgentId ?? undefined,
      turnId: activePendingTurn?.turnId,
    });
  }, [activeRepoAgentId, pendingTurns, sessionId, voice]);

  const connect = useCallback(() => {
    connectRequestedRef.current = true;
    setConnectionState('connecting');
    if (voice.socketConnected) {
      voice.sendClientMessage({
        type: 'SESSION_START',
        sessionId: sessionId ?? undefined,
        enableAudio: true,  // Web app uses audio playback
      });
    }
  }, [sessionId, voice]);

  const activeAgent = useMemo<Agent>(() => {
    if (!activeAgentSummary) {
      return EMPTY_AGENT;
    }
    return {
      id: activeAgentSummary.repoAgentId,
      name: activeAgentSummary.displayName,
      status: activeAgentSummary.status,
    };
  }, [activeAgentSummary]);

  const sendMessage = useCallback(
    (text: string) => {
      voice.sendTranscript(text, {
        sessionId: sessionId ?? undefined,
        repoAgentId: activeRepoAgentId ?? undefined,
        turnId: pendingTurns.find(
          (turn) =>
            turn.repoAgentId === activeRepoAgentId &&
            turn.requiresUserResponse,
        )?.turnId,
      });
    },
    [activeRepoAgentId, pendingTurns, sessionId, voice],
  );

  const approveAction = useCallback(
    (id: string) => {
      const pendingTurn = pendingTurns.find((turn) => turn.turnId === id);
      if (!pendingTurn) {
        return;
      }
      voice.sendTranscript('yes', {
        sessionId: sessionId ?? undefined,
        repoAgentId: pendingTurn.repoAgentId,
        turnId: pendingTurn.turnId,
      });
    },
    [pendingTurns, sessionId, voice],
  );

  const rejectAction = useCallback(
    (id: string) => {
      const pendingTurn = pendingTurns.find((turn) => turn.turnId === id);
      if (!pendingTurn) {
        return;
      }
      voice.sendTranscript('no', {
        sessionId: sessionId ?? undefined,
        repoAgentId: pendingTurn.repoAgentId,
        turnId: pendingTurn.turnId,
      });
    },
    [pendingTurns, sessionId, voice],
  );

  const approvals = useMemo<ApprovalRequest[]>(
    () =>
      pendingTurns
        .filter((turn) => turn.requiresUserResponse)
        .map((turn) => ({
          id: turn.turnId,
          repoAgentId: turn.repoAgentId,
          title: `${turn.repoName} needs attention`,
          description: turn.message,
          metadata: {
            repoAgentId: turn.repoAgentId,
            turnId: turn.turnId,
            type: turn.type,
          },
        })),
    [pendingTurns],
  );

  return {
    connectionState,
    socketConnected: voice.socketConnected,
    listening: voice.listening,
    speaking: voice.speaking,
    transcript: voice.transcript,
    getVolume: voice.getVolume,
    messages,
    activeAgent,
    approvals,
    connect,
    sendMessage,
    approveAction,
    rejectAction,
  };
}

function handleServerMessage(
  message: ServerToClientMessage,
  setSessionId: (value: string | null) => void,
  setConnectionState: (
    value: 'disconnected' | 'connecting' | 'connected',
  ) => void,
  setActiveRepoAgentId: (value: string | null) => void,
  setMessages: (value: Message[] | ((prev: Message[]) => Message[])) => void,
  setPendingTurns: (
    value:
      | PendingTurnSummary[]
      | ((prev: PendingTurnSummary[]) => PendingTurnSummary[]),
  ) => void,
  setActiveAgentSummary: (value: RepoSummary | null) => void,
) {
  if (message.type === 'SESSION_STATE') {
    const state = message as SessionStateMessage;
    setSessionId(state.sessionId);
    setConnectionState('connected');
    setActiveRepoAgentId(state.activeRepoAgentId ?? null);
    setActiveAgentSummary(state.activeAgent ?? null);
    setMessages(state.messages.map(mapVoiceChatMessage));
    setPendingTurns(state.pendingTurns);
    return;
  }

  if (message.type === 'CHAT_MESSAGE') {
    const chatMessage = message as VoiceChatMessage;
    setMessages((prev) => upsertMessage(prev, mapVoiceChatMessage(chatMessage)));
    return;
  }

  if (message.type === 'PENDING_TURN') {
    const pending = (message as PendingTurnMessage).pendingTurn;
    setPendingTurns((prev) => upsertPendingTurn(prev, pending));
  }
}

function mapVoiceChatMessage(message: VoiceChatMessage): Message {
  return {
    id: message.id,
    role: message.role,
    content: message.content,
  };
}

function upsertMessage(messages: Message[], next: Message): Message[] {
  const existing = messages.findIndex((item) => item.id === next.id);
  if (existing === -1) {
    return [...messages, next];
  }
  return messages.map((item, index) => (index === existing ? next : item));
}

function upsertPendingTurn(
  pendingTurns: PendingTurnSummary[],
  next: PendingTurnSummary,
): PendingTurnSummary[] {
  const existing = pendingTurns.findIndex((item) => item.turnId === next.turnId);
  if (existing === -1) {
    return [...pendingTurns, next];
  }
  return pendingTurns.map((item, index) =>
    index === existing ? next : item,
  );
}
