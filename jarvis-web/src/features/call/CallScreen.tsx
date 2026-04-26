import { useEffect, useState } from 'react';
import { CallButton } from './CallButton';
import { JarvisOrb } from './JarvisOrb';
import type { OrbCallState } from './JarvisOrb';
import { useConversationLoop } from './useConversationLoop';
import type { Message, Agent/*, ApprovalRequest*/ } from '../../shared/types';
import type { RepoSummary } from '../../voice/types/protocol';

type Props = {
  socketConnected: boolean;
  listening: boolean;
  speaking: boolean;
  transcript: string;
  messages: Message[];
  repos: RepoSummary[];
  activeRepoAgentId: string | null;
  activeAgent: Agent;
  getVolume: () => number;
  // approvals: ApprovalRequest[];
  onSendMessage: (text: string) => void;
  onSwitchRepository: (repoAgentId: string) => boolean;
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
  repos,
  activeRepoAgentId,
  activeAgent,
  getVolume,
  // approvals,
  onSwitchRepository,
}: Props) {
  const { inCall, startCall, endCall } = useConversationLoop();
  const timer = useCallTimer(inCall);

  type CallState = OrbCallState;
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
  const totalPendingTurns = repos.reduce((acc, repo) => acc + repo.pendingTurns, 0);

  return (
    <div className="jv-screen jv-call-screen">

      {/* ── Full-screen 3D canvas (background layer) ── */}
      <JarvisOrb callState={callState} getVolume={getVolume} />

      {/* ── HUD overlay (sits above canvas) ── */}
      <div className="jv-call-hud">

        {/* Corner brackets */}
        <div className="jv-hud-corner jv-hud-corner--tl" />
        <div className="jv-hud-corner jv-hud-corner--tr" />
        <div className="jv-hud-corner jv-hud-corner--bl" />
        <div className="jv-hud-corner jv-hud-corner--br" />

        {/* Header */}
        <header className="jv-call-header">
          <span className={`jv-dot ${socketConnected ? 'jv-dot--ok' : 'jv-dot--err'}`} />
          <span className="jv-call-agent">{activeAgent.name}</span>
          <select
            className="jv-repo-select"
            value={activeRepoAgentId ?? ''}
            disabled={repos.length === 0}
            onChange={(event) => {
              const nextRepoAgentId = event.target.value;
              if (nextRepoAgentId) {
                onSwitchRepository(nextRepoAgentId);
              }
            }}
            aria-label="Active repository"
          >
            <option value="" disabled>
              Select repository
            </option>
            {repos.map((repo) => {
              const pendingLabel = repo.pendingTurns > 0 ? ` (${repo.pendingTurns})` : '';
              return (
                <option key={repo.repoAgentId} value={repo.repoAgentId}>
                  {repo.displayName}{pendingLabel}
                </option>
              );
            })}
          </select>
          {totalPendingTurns > 0 && (
            <span className="jv-pending-chip" aria-label={`${totalPendingTurns} pending turns`}>
              {totalPendingTurns} pending
            </span>
          )}
          {inCall && (
            <span className="jv-call-timer" style={{ marginLeft: 'auto' }}>
              <span className="jv-dot jv-dot--ok" style={{ display: 'inline-block', marginRight: 6 }} />
              {timer}
            </span>
          )}
        </header>

        {/* Centre labels — float over orb */}
        <main className="jv-call-body">
          <p className="jv-call-state-label">{stateLabel[callState]}</p>
          {subtitle && <p className="jv-call-subtitle">{subtitle}</p>}
        </main>

        {/* Footer */}
        <footer className="jv-call-footer">
          <CallButton inCall={inCall} onStart={startCall} onEnd={endCall} />
        </footer>

      </div>
    </div>
  );
}
