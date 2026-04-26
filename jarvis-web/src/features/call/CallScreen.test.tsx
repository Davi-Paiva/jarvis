import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { CallScreen } from './CallScreen'

vi.mock('./JarvisOrb', () => ({
  JarvisOrb: ({ callState }: { callState: string }) => (
    <div data-testid="orb-state">{callState}</div>
  ),
}))

vi.mock('./useConversationLoop', () => ({
  useConversationLoop: () => ({
    inCall: true,
    startCall: vi.fn(),
    endCall: vi.fn(),
  }),
}))

describe('CallScreen', () => {
  it('reflects the active agent state and latest assistant response', () => {
    render(
      <CallScreen
        socketConnected
        listening={false}
        speaking={false}
        transcript=""
        messages={[
          {
            id: 'msg-1',
            role: 'assistant',
            content: 'Approval pending for alpha-app.',
          },
        ]}
        repos={[
          {
            repoAgentId: 'repo-1',
            repoId: 'repo-record-1',
            displayName: 'alpha-app',
            repoPath: '/tmp/alpha-app',
            phase: 'PLANNING',
            status: 'running',
            pendingTurns: 1,
          },
        ]}
        activeRepoAgentId="repo-1"
        activeAgent={{
          id: 'repo-1',
          name: 'alpha-app',
          status: 'running',
        }}
        getVolume={() => 0}
        onSendMessage={() => undefined}
        onSwitchRepository={() => true}
      />,
    )

    expect(screen.getByText('alpha-app')).toBeInTheDocument()
    expect(screen.getByText('Jarvis is thinking...')).toBeInTheDocument()
    expect(screen.getByText('Approval pending for alpha-app.')).toBeInTheDocument()
    expect(screen.getByTestId('orb-state')).toHaveTextContent('thinking')
  })
})
