import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react'
import { useSpeechToText } from '../hooks/useSpeechToText.ts'
import { useTextToSpeech } from '../hooks/useTextToSpeech.ts'
import { appSocket } from '../services/socket.ts'

type VoiceContextValue = {
  listening: boolean
  speaking: boolean
  transcript: string
  socketConnected: boolean
  loopbackMode: boolean
  startListening: () => void
  stopListening: () => void
  sendTranscript: (text: string) => boolean
}

const VoiceContext = createContext<VoiceContextValue | undefined>(undefined)

type VoiceProviderProps = {
  children: ReactNode
  socket?: WebSocket
}

type SocketAIResponse = {
  type?: string
  responseText?: string
  text?: string
  payload?: string | { text?: string; responseText?: string }
}

function extractAIResponseText(message: SocketAIResponse): string {
  if (typeof message.responseText === 'string') {
    return message.responseText
  }

  if (typeof message.text === 'string') {
    return message.text
  }

  if (typeof message.payload === 'string') {
    return message.payload
  }

  if (typeof message.payload === 'object' && message.payload !== null) {
    if (typeof message.payload.responseText === 'string') {
      return message.payload.responseText
    }

    if (typeof message.payload.text === 'string') {
      return message.payload.text
    }
  }

  return ''
}

export function VoiceProvider({ children, socket = appSocket }: VoiceProviderProps) {
  const [transcript, setTranscript] = useState('')
  const [socketConnected, setSocketConnected] = useState(
    socket.readyState === WebSocket.OPEN,
  )
  const lastSentRef = useRef<{ text: string; at: number }>({ text: '', at: 0 })
  const loopbackMode = import.meta.env.VITE_VOICE_LOCAL_LOOPBACK === 'true'

  const { speak, stop, isSpeaking } = useTextToSpeech()

  useEffect(() => {
    const onOpen = () => setSocketConnected(true)
    const onClose = () => setSocketConnected(false)

    socket.addEventListener('open', onOpen)
    socket.addEventListener('close', onClose)

    return () => {
      socket.removeEventListener('open', onOpen)
      socket.removeEventListener('close', onClose)
    }
  }, [socket])

  const sendTranscript = useCallback(
    (text: string) => {
      const normalized = text.trim()
      if (!normalized) {
        return false
      }

      const now = Date.now()
      const duplicateSend =
        normalized === lastSentRef.current.text && now - lastSentRef.current.at < 1500

      if (duplicateSend) {
        return false
      }

      if (socket.readyState === WebSocket.OPEN) {
        socket.send(
          JSON.stringify({
            type: 'USER_TRANSCRIPT',
            text: normalized,
          }),
        )
      } else if (loopbackMode) {
        const simulatedText = `You said: ${normalized}`
        setTimeout(() => {
          void speak(simulatedText)
        }, 300)
      } else {
        return false
      }

      lastSentRef.current = { text: normalized, at: now }
      setTranscript('')
      return true
    },
    [loopbackMode, socket, speak],
  )

  const { transcript: liveTranscript, isListening, startListening: startSTT, stopListening: stopSTT } =
    useSpeechToText({
      onFinalTranscript: (text) => {
        setTranscript(text)
        sendTranscript(text)
      },
    })

  useEffect(() => {
    if (liveTranscript) {
      setTranscript(liveTranscript)
    }
  }, [liveTranscript])

  useEffect(() => {
    const onMessage = (event: MessageEvent<string>) => {
      let payload: SocketAIResponse

      try {
        payload = JSON.parse(event.data) as SocketAIResponse
      } catch {
        return
      }

      if (payload.type !== 'AI_RESPONSE') {
        return
      }

      const responseText = extractAIResponseText(payload)
      if (!responseText) {
        return
      }

      void speak(responseText)
    }

    socket.addEventListener('message', onMessage)
    return () => {
      socket.removeEventListener('message', onMessage)
    }
  }, [socket, speak])

  const startListening = useCallback(() => {
    if (isSpeaking) {
      stop()
    }
    startSTT()
  }, [isSpeaking, startSTT, stop])

  const value = useMemo<VoiceContextValue>(
    () => ({
      listening: isListening,
      speaking: isSpeaking,
      transcript,
      socketConnected,
      loopbackMode,
      startListening,
      stopListening: stopSTT,
      sendTranscript,
    }),
    [
      isListening,
      isSpeaking,
      transcript,
      socketConnected,
      loopbackMode,
      startListening,
      stopSTT,
      sendTranscript,
    ],
  )

  return <VoiceContext.Provider value={value}>{children}</VoiceContext.Provider>
}

export function useVoice(): VoiceContextValue {
  const context = useContext(VoiceContext)

  if (!context) {
    throw new Error('useVoice must be used inside VoiceProvider')
  }

  return context
}
