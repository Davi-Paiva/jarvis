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
  AudioStreamChunkMessage,
  AudioStreamEndMessage,
  AudioStreamStartMessage,
  ServerToClientMessage,
  UserTranscriptMessage,
} from '../types/protocol.ts'

// ── Streaming state types ─────────────────────────────────────────────────────

// Used on the accumulate path (non-PCM fallback): collect all chunks then play
// the complete blob when AUDIO_STREAM_END arrives.
type FallbackAccumulator = {
  turnId: string
  byteChunks: Uint8Array<ArrayBuffer>[]
  responseText: string
}

// ── Module-level utilities ────────────────────────────────────────────────────

function base64ToArrayBuffer(b64: string): ArrayBuffer {
  const binary = atob(b64)
  const bytes = new Uint8Array(binary.length)
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i)
  return bytes.buffer
}

// ── Context type ──────────────────────────────────────────────────────────────

type VoiceContextValue = {
  listening: boolean
  speaking: boolean
  transcript: string
  socketConnected: boolean
  loopbackMode: boolean
  getVolume: () => number
  startListening: () => void
  stopListening: () => void
  sendTranscript: (text: string) => boolean
}

const VoiceContext = createContext<VoiceContextValue | undefined>(undefined)

type VoiceProviderProps = {
  children: ReactNode
  socket?: WebSocket
}

// ── Provider ──────────────────────────────────────────────────────────────────

export function VoiceProvider({ children, socket = appSocket }: VoiceProviderProps) {
  const [transcript, setTranscript] = useState('')
  const [socketConnected, setSocketConnected] = useState(
    socket.readyState === WebSocket.OPEN,
  )
  const lastSentRef = useRef<{ text: string; at: number }>({ text: '', at: 0 })
  const loopbackMode = import.meta.env.VITE_VOICE_LOCAL_LOOPBACK === 'true'

  // Stream state refs — which path is active for the current turn.
  const streamModeRef = useRef<'pcm' | 'accumulate' | null>(null)
  const streamResponseTextRef = useRef<string>('')
  const fallbackAccRef = useRef<FallbackAccumulator | null>(null)

  const { speak, stop, isSpeaking } = useTextToSpeech()
  const {
    unlock,
    playFromUrl,
    playFromBase64,
    stop: stopAudio,
    isPlaying: isAudioPlaying,
    getVolume,
    initPcmStream,
    appendPcmChunk,
  } = useAudioPlayback()

  // ── Socket open / close ───────────────────────────────────────────────────
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

  // ── Stream cleanup ────────────────────────────────────────────────────────
  // Called before a new stream starts (superseding) and on barge-in / unmount.
  const cleanupStream = useCallback(() => {
    stopAudio()
    streamModeRef.current = null
    streamResponseTextRef.current = ''
    fallbackAccRef.current = null
  }, [stopAudio])

  // Revoke object URLs on unmount.
  useEffect(() => () => { cleanupStream() }, [cleanupStream])

  // ── Transcript send ───────────────────────────────────────────────────────
  const sendTranscript = useCallback(
    (text: string) => {
      const normalized = text.trim()
      if (!normalized) return false

      const now = Date.now()
      const duplicateSend =
        normalized === lastSentRef.current.text && now - lastSentRef.current.at < 1500
      if (duplicateSend) return false

      if (socket.readyState === WebSocket.OPEN) {
        const message: UserTranscriptMessage = { type: 'USER_TRANSCRIPT', text: normalized }
        socket.send(JSON.stringify(message))
      } else if (loopbackMode) {
        const simulatedText = `You said: ${normalized}`
        setTimeout(() => { void speak(simulatedText) }, 300)
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
    if (liveTranscript) setTranscript(liveTranscript)
  }, [liveTranscript])

  // ── WebSocket message handler ─────────────────────────────────────────────
  useEffect(() => {
    const onMessage = async (event: MessageEvent<string>) => {
      let payload: ServerToClientMessage
      try {
        payload = JSON.parse(event.data) as ServerToClientMessage
      } catch {
        return
      }

      // ── Legacy path: full audio blob in one message (AI_RESPONSE) ─────────
      // Unchanged from original behaviour; used as fallback when backend
      // does not support streaming.
      if (payload.type === 'AI_RESPONSE') {
        const message = payload as AIResponseMessage
        const responseText = message.responseText?.trim()
        if (!responseText) return

        cleanupStream()
        stop()

        if (message.audioUrl) {
          const played = await playFromUrl(message.audioUrl)
          if (played) return
        }
        if (message.audioBase64) {
          const played = await playFromBase64(message.audioBase64, message.audioMimeType)
          if (played) return
        }
        await speak(responseText)
        return
      }

      // ── Streaming path: AUDIO_STREAM_START ───────────────────────────────
      // Backend signals start of a new turn.
      // PCM path  (encoding === 'pcm16le'): schedule chunks directly via Web
      //           Audio API — no codec framing, gapless, no MSE required.
      // Fallback  (any other encoding): accumulate all chunks, play on END.
      if (payload.type === 'AUDIO_STREAM_START') {
        const msg = payload as AudioStreamStartMessage
        cleanupStream()  // stop previous audio and reset state
        stop()           // stop any browser TTS

        streamResponseTextRef.current = msg.responseText ?? ''

        if (msg.encoding === 'pcm16le' && msg.sampleRate) {
          streamModeRef.current = 'pcm'
          initPcmStream(msg.sampleRate, msg.turnId)
        } else {
          // Accumulate fallback — plays when END arrives.
          streamModeRef.current = 'accumulate'
          fallbackAccRef.current = {
            turnId: msg.turnId,
            byteChunks: [],
            responseText: msg.responseText ?? '',
          }
        }
        return
      }

      // ── Streaming path: AUDIO_STREAM_CHUNK ───────────────────────────────
      if (payload.type === 'AUDIO_STREAM_CHUNK') {
        const msg = payload as AudioStreamChunkMessage

        if (streamModeRef.current === 'pcm') {
          appendPcmChunk(msg.audioBase64, msg.turnId)
        } else {
          const acc = fallbackAccRef.current
          if (!acc || acc.turnId !== msg.turnId) return
          const buffer = base64ToArrayBuffer(msg.audioBase64)
          acc.byteChunks.push(new Uint8Array(buffer) as Uint8Array<ArrayBuffer>)
        }
        return
      }

      // ── Streaming path: AUDIO_STREAM_END ─────────────────────────────────
      if (payload.type === 'AUDIO_STREAM_END') {
        const msg = payload as AudioStreamEndMessage

        if (streamModeRef.current === 'pcm') {
          // PCM sources are already scheduled; nothing to do on END unless
          // the stream errored before any chunks arrived.
          if (msg.error && msg.totalChunks === 0) {
            const rt = streamResponseTextRef.current
            cleanupStream()
            await speak(rt)
          }

        } else {
          const acc = fallbackAccRef.current
          if (!acc || acc.turnId !== msg.turnId) return
          fallbackAccRef.current = null

          if (acc.byteChunks.length === 0) {
            await speak(acc.responseText)
            return
          }

          // Combine all byte slices into a single Blob and play.
          const blob = new Blob(acc.byteChunks, { type: 'audio/mpeg' })
          const url = URL.createObjectURL(blob)
          const played = await playFromUrl(url)
          URL.revokeObjectURL(url)
          if (!played) await speak(acc.responseText)
        }
        return
      }
    }

    socket.addEventListener('message', onMessage)
    return () => { socket.removeEventListener('message', onMessage) }
  }, [appendPcmChunk, cleanupStream, initPcmStream, playFromBase64, playFromUrl, socket, speak, stop, stopAudio])

  // ── Start / stop listening ────────────────────────────────────────────────
  const startListening = useCallback(() => {
    void unlock()

    // Barge-in: stop any ongoing playback and discard the current stream.
    if (isSpeaking || isAudioPlaying) {
      stop()
      stopAudio()
    }
    cleanupStream()
    startSTT()
  }, [cleanupStream, isAudioPlaying, isSpeaking, startSTT, stop, stopAudio, unlock])

  const value = useMemo<VoiceContextValue>(
    () => ({
      listening: isListening,
      speaking: isSpeaking || isAudioPlaying,
      transcript,
      socketConnected,
      loopbackMode,
      getVolume,
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
      getVolume,
      startListening,
      stopSTT,
      sendTranscript,
    ],
  )

  return <VoiceContext.Provider value={value}>{children}</VoiceContext.Provider>
}

export function useVoice(): VoiceContextValue {
  const context = useContext(VoiceContext)
  if (!context) throw new Error('useVoice must be used inside VoiceProvider')
  return context
}

