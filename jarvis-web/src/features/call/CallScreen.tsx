import { useEffect, useState } from 'react';
import { VoiceButton } from '../../voice/components/VoiceButton';
import type { Message, Agent/*, ApprovalRequest*/ } from '../../shared/types';

type Props = {
  socketConnected: boolean;
  listening: boolean;
  speaking: boolean;
  transcript: string;
  messages: Message[];
  activeAgent: Agent;
  // approvals: ApprovalRequest[];
  onSendMessage: (text: string) => void;
};

function useCallTimer() {
  const [seconds, setSeconds] = useState(0);
  useEffect(() => {
    const id = setInterval(() => setSeconds(s => s + 1), 1000);
    return () => clearInterval(id);
  }, []);
  const m = String(Math.floor(seconds / 60)).padStart(2, '0');
  const s = String(seconds % 60).padStart(2, '0');
  return `${m}:${s}`;
}

export function CallScreen({
  socketConnected,
  listening,
  speaking,
  transcript,
  messages,
  activeAgent,
  // approvals,
}: Props) {
  const timer = useCallTimer();

  // Derive state for orb + label
  const callState: 'listening' | 'thinking' | 'responding' | 'idle' = listening
    ? 'listening'
    : speaking
    ? 'responding'
    : activeAgent.status === 'running'
    ? 'thinking'
    : 'idle';

  const stateLabel: Record<typeof callState, string> = {
    listening:  'Listening...',
    thinking:   'Jarvis is thinking...',
    responding: 'Jarvis is responding...',
    idle:       'Call in progress',
  };

  // Subtitle: live transcript first, otherwise last assistant message
  const lastAI = [...messages].reverse().find(m => m.role === 'assistant');
  const subtitle = transcript || lastAI?.content || '';

  return (
    <div className="jv-screen jv-call-screen">
      {/* Header */}
      <header className="jv-call-header">
        <span className={`jv-dot ${socketConnected ? 'jv-dot--ok' : 'jv-dot--err'}`} />
        <span className="jv-call-agent">{activeAgent.name}</span>
        {/* approvals.length > 0 && (
          <span className="jv-badge jv-badge--warn" style={{ marginLeft: 'auto' }}>
            {approvals.length} pending
          </span>
        ) */}
      </header>

      {/* Call body */}
      <main className="jv-call-body">
        {/* Orb */}
        <div className={`jv-orb jv-orb--${callState}`}>
          <div className="jv-orb-inner" />
        </div>

        {/* State label */}
        <p className="jv-call-state-label">{stateLabel[callState]}</p>

        {/* Subtitle — last spoken text, fades in/out */}
        {subtitle && (
          <p className="jv-call-subtitle">{subtitle}</p>
        )}
      </main>

      {/* Footer */}
      <footer className="jv-call-footer">
        <VoiceButton />
        <p className="jv-call-timer">
          <span className={`jv-dot jv-dot--ok`} style={{ display: 'inline-block', marginRight: 6 }} />
          {timer}
        </p>
      </footer>
    </div>
  );
}
