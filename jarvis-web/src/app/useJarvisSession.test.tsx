import { act, fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { PendingTurnSummary } from '../voice/types/protocol'
import { VoiceProvider } from '../voice/context/VoiceProvider'
import { MockWebSocket } from '../test/MockWebSocket'
import { useJarvisSession } from './useJarvisSession'

function SessionHarness() {
  const session = useJarvisSession()

  return (
    <div>
      <div data-testid="connection">{session.connectionState}</div>
      <div data-testid="agent">{session.activeAgent.name}</div>
      <div data-testid="messages">{String(session.messages.length)}</div>
      <div data-testid="approvals">{String(session.approvals.length)}</div>
      <button type="button" onClick={session.connect}>
        connect
      </button>
      <button
        type="button"
        onClick={() =>
          session.approvals[0] && session.approveAction(session.approvals[0].id)
        }
      >
        approve
      </button>
    </div>
  )
}

describe('useJarvisSession', () => {
  it('hydrates state from websocket messages and sends approval replies', () => {
    const socket = new MockWebSocket()

    render(
      <VoiceProvider socket={socket as unknown as WebSocket}>
        <SessionHarness />
      </VoiceProvider>,
    )

    act(() => {
      socket.emitOpen()
    })

    fireEvent.click(screen.getByText('connect'))
    expect(JSON.parse(socket.sent[0])).toEqual({ type: 'SESSION_START' })

    act(() => {
      socket.emitMessage({
        type: 'SESSION_STATE',
        sessionId: 'session-1',
        activeRepoAgentId: 'repo-1',
        activeChatId: 'chat-1',
        repos: [
          {
            repoAgentId: 'repo-1',
            repoId: 'repo-record-1',
            displayName: 'alpha-app',
            repoPath: '/tmp/alpha-app',
            phase: 'WAITING_APPROVAL',
            status: 'waiting_approval',
            pendingTurns: 1,
          },
        ],
        activeAgent: {
          repoAgentId: 'repo-1',
          repoId: 'repo-record-1',
          displayName: 'alpha-app',
          repoPath: '/tmp/alpha-app',
          phase: 'WAITING_APPROVAL',
          status: 'waiting_approval',
          pendingTurns: 1,
        },
        pendingTurns: [],
        messages: [
          {
            type: 'CHAT_MESSAGE',
            id: 'msg-1',
            chatId: 'chat-1',
            repoAgentId: 'repo-1',
            role: 'assistant',
            content: 'Plan ready.',
            createdAt: '2026-04-25T00:00:00Z',
          },
        ],
      })
    })

    expect(screen.getByTestId('connection')).toHaveTextContent('connected')
    expect(screen.getByTestId('agent')).toHaveTextContent('alpha-app')
    expect(screen.getByTestId('messages')).toHaveTextContent('1')

    const pendingTurn: PendingTurnSummary = {
      turnId: 'turn-1',
      repoAgentId: 'repo-1',
      repoName: 'alpha-app',
      type: 'APPROVAL',
      message: 'Approve this plan?',
      requiresUserResponse: true,
      priority: 60,
      createdAt: '2026-04-25T00:00:01Z',
    }

    act(() => {
      socket.emitMessage({
        type: 'PENDING_TURN',
        pendingTurn,
      })
    })

    expect(screen.getByTestId('approvals')).toHaveTextContent('1')

    fireEvent.click(screen.getByText('approve'))

    const approvalReply = JSON.parse(socket.sent[socket.sent.length - 1])
    expect(approvalReply).toMatchObject({
      type: 'USER_TRANSCRIPT',
      text: 'yes',
      sessionId: 'session-1',
      repoAgentId: 'repo-1',
      turnId: 'turn-1',
    })
  })
})
