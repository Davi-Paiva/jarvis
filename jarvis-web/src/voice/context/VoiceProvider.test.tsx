import { act, fireEvent, render, screen } from '@testing-library/react'
import { useEffect, useState } from 'react'
import { describe, expect, it } from 'vitest'
import { MockWebSocket } from '../../test/MockWebSocket'
import { VoiceProvider, useVoice } from './VoiceProvider'

function VoiceConsumer() {
  const voice = useVoice()
  const [lastMessageType, setLastMessageType] = useState('none')

  useEffect(() => {
    return voice.addServerMessageListener((message) => {
      setLastMessageType(message.type)
    })
  }, [voice])

  return (
    <div>
      <div data-testid="connected">{String(voice.socketConnected)}</div>
      <div data-testid="last-message-type">{lastMessageType}</div>
      <button
        type="button"
        onClick={() => voice.sendClientMessage({ type: 'SESSION_START' })}
      >
        send
      </button>
    </div>
  )
}

describe('VoiceProvider', () => {
  it('tracks socket state and forwards server messages to listeners', () => {
    const socket = new MockWebSocket()

    render(
      <VoiceProvider socket={socket as unknown as WebSocket}>
        <VoiceConsumer />
      </VoiceProvider>,
    )

    expect(screen.getByTestId('connected')).toHaveTextContent('false')

    act(() => {
      socket.emitOpen()
    })

    expect(screen.getByTestId('connected')).toHaveTextContent('true')

    fireEvent.click(screen.getByText('send'))
    expect(JSON.parse(socket.sent[0])).toEqual({ type: 'SESSION_START' })

    act(() => {
      socket.emitMessage({
        type: 'SESSION_STATE',
        sessionId: 'session-1',
        repos: [],
        pendingTurns: [],
        messages: [],
      })
    })

    expect(screen.getByTestId('last-message-type')).toHaveTextContent(
      'SESSION_STATE',
    )
  })
})
