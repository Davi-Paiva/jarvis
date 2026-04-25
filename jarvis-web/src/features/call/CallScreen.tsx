import { useEffect, useState } from 'react';
import { CallButton } from './CallButton';
import { useConversationLoop } from './useConversationLoop';
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

function useCallTimer(active: boolean) {
  const [seconds, setSeconds] = useState(0);
  useEffect(() => {
    if (!active) { setSeconds(0); return; }
    const id = setInterval(() => setSeconds(s => s + 1), 1000);
    return () => clearInterval(id);
  }, [active]);
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
  const { inCall, startCall, endCall } = useConversationLoop();
  const timer = useCallTimer(inCall);

  type CallState = 'inactive' | 'listening' | 'thinking' | 'responding';
  const callState: CallState = !inCall
    ? 'inactive'
    : listening
    ? 'listening'
    : speaking
    ? 'responding'
    : activeAgent.status === 'running'
    ? 'thinking'
    : 'listening'; // default back to listening when idle mid-call

  const stateLabel: Record<CallState, string> = {
    inactive:   'Tap to start a call',
    listening:  'Listening...',
    thinking:   'Jarvis is thinking...',
    responding: 'Jarvis is responding...',
  };

  // Subtitle: live transcript first, otherwise last assistant message
  const lastAI = [...messages].reverse().find(m => m.role === 'assistant');
  const subtitle = transcript || (inCall ? lastAI?.content ?? '' : '');

  return (
    <div className="jv-screen jv-call-screen">
      {/* Header */}
      <header className="jv-call-header">
        <span className={`jv-dot ${socketConnected ? 'jv-dot--ok' : 'jv-dot--err'}`} />
        <span className="jv-call-agent">{activeAgent.name}</span>
        {inCall && (
          <span className="jv-call-timer" style={{ marginLeft: 'auto' }}>
            <span className="jv-dot jv-dot--ok" style={{ display: 'inline-block', marginRight: 6 }} />
            {timer}
          </span>
        )}
      </header>

      {/* Call body */}
      <main className="jv-call-body">
        <div className={`jv-orb jv-orb--${callState}`}>
          <div className="jv-orb-inner" />
        </div>

        <p className="jv-call-state-label">{stateLabel[callState]}</p>

        {subtitle && (
          <p className="jv-call-subtitle">{subtitle}</p>
        )}
      </main>

      {/* Footer */}
      <footer className="jv-call-footer">
        <CallButton inCall={inCall} onStart={startCall} onEnd={endCall} />
      </footer>
    </div>
  );
}
