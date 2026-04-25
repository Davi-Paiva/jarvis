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
import { useAudioPlayback } from '../hooks/useAudioPlayback.ts'
import { appSocket } from '../services/socket.ts'
import type {
  AIResponseMessage,
  ServerToClientMessage,
  UserTranscriptMessage,
} from '../types/protocol.ts'

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

export function VoiceProvider({ children, socket = appSocket }: VoiceProviderProps) {
  const [transcript, setTranscript] = useState('')
  const [socketConnected, setSocketConnected] = useState(
    socket.readyState === WebSocket.OPEN,
  )
  const lastSentRef = useRef<{ text: string; at: number }>({ text: '', at: 0 })
  const loopbackMode = import.meta.env.VITE_VOICE_LOCAL_LOOPBACK === 'true'

  const { speak, stop, isSpeaking } = useTextToSpeech()
  const {
    unlock,
    playFromUrl,
    playFromBase64,
    stop: stopAudio,
    isPlaying: isAudioPlaying,
  } = useAudioPlayback()

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
        const message: UserTranscriptMessage = {
          type: 'USER_TRANSCRIPT',
          text: normalized,
        }

        socket.send(
          JSON.stringify(message),
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
    const onMessage = async (event: MessageEvent<string>) => {
      let payload: ServerToClientMessage

      try {
        payload = JSON.parse(event.data) as ServerToClientMessage
      } catch {
        return
      }

      if (payload.type !== 'AI_RESPONSE') {
        return
      }

      const message = payload as AIResponseMessage
      const responseText = message.responseText?.trim()
      if (!responseText) {
        return
      }

      stop()

      if (message.audioUrl) {
        const played = await playFromUrl(message.audioUrl)
        if (played) {
          return
        }
      }

      if (message.audioBase64) {
        const played = await playFromBase64(message.audioBase64, message.audioMimeType)
        if (played) {
          return
        }
      }

      await speak(responseText)
    }

    socket.addEventListener('message', onMessage)
    return () => {
      socket.removeEventListener('message', onMessage)
    }
  }, [playFromBase64, playFromUrl, socket, speak, stop])

  const startListening = useCallback(() => {
    void unlock()

    if (isSpeaking || isAudioPlaying) {
      stop()
      stopAudio()
    }
    startSTT()
  }, [isAudioPlaying, isSpeaking, startSTT, stop, stopAudio, unlock])

  const value = useMemo<VoiceContextValue>(
    () => ({
      listening: isListening,
      speaking: isSpeaking || isAudioPlaying,
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
      isAudioPlaying,
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
