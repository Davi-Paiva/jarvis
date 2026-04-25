import { useState, useCallback } from 'react';
import { useVoice } from '../voice/context/VoiceProvider';
import type { Message, ApprovalRequest, Agent } from '../shared/types';

// ── Mock data – lets you test every screen without a live backend ──────────
const MOCK_MESSAGES: Message[] = [
  { id: '1', role: 'system', content: 'Session started' },
  { id: '2', role: 'assistant', content: "Hello! I'm Jarvis. How can I help you today?" },
  { id: '3', role: 'user', content: 'Can you refactor the auth module?' },
  { id: '4', role: 'assistant', content: 'Analysing the auth module now...', streaming: true },
];

const MOCK_APPROVALS: ApprovalRequest[] = [
  {
    id: 'apr-1',
    title: 'Delete legacy file',
    description: 'Remove auth/legacy.ts — this file is unused and referenced nowhere.',
    affectedFiles: ['src/auth/legacy.ts'],
  },
];

const ACTIVE_AGENT: Agent = { id: 'agent-1', name: 'Jarvis', status: 'running' };
// ──────────────────────────────────────────────────────────────────────────

export function useJarvisSession() {
  const voice = useVoice();

  const [sessionConnected, setSessionConnected] = useState(false);
  const [messages, setMessages] = useState<Message[]>(MOCK_MESSAGES);
  const [approvals, setApprovals] = useState<ApprovalRequest[]>(MOCK_APPROVALS);

  // Accepts any non-empty pairing code (placeholder validation)
  const connect = useCallback((code: string) => {
    if (code.trim().length > 0) setSessionConnected(true);
  }, []);

  const sendMessage = useCallback(
    (text: string) => {
      const msg: Message = { id: Date.now().toString(), role: 'user', content: text };
      setMessages(prev => [...prev, msg]);
      voice.sendTranscript(text);
    },
    [voice],
  );

  const approveAction = useCallback(
    (id: string) => setApprovals(prev => prev.filter(a => a.id !== id)),
    [],
  );

  const rejectAction = useCallback(
    (id: string) => setApprovals(prev => prev.filter(a => a.id !== id)),
    [],
  );

  return {
    connectionState: sessionConnected ? 'connected' : 'disconnected',
    socketConnected: voice.socketConnected,
    listening: voice.listening,
    speaking: voice.speaking,
    transcript: voice.transcript,
    messages,
    activeAgent: ACTIVE_AGENT,
    approvals,
    connect,
    sendMessage,
    approveAction,
    rejectAction,
  };
}
