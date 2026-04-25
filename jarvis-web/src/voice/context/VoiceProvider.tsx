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
import { createAppSocket } from '../services/socket.ts'
import type {
  AIResponseMessage,
<<<<<<< Updated upstream
  AudioStreamChunkMessage,
  AudioStreamEndMessage,
  AudioStreamStartMessage,
=======
  ClientToServerMessage,
>>>>>>> Stashed changes
  ServerToClientMessage,
  UserTranscriptMessage,
} from '../types/protocol.ts'

<<<<<<< Updated upstream
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

=======
type TranscriptContext = {
  sessionId?: string
  repoAgentId?: string
  turnId?: string
}

>>>>>>> Stashed changes
type VoiceContextValue = {
  listening: boolean
  speaking: boolean
  transcript: string
  socketConnected: boolean
  loopbackMode: boolean
  getVolume: () => number
  startListening: () => void
  stopListening: () => void
  sendTranscript: (text: string, context?: TranscriptContext) => boolean
  sendClientMessage: (message: ClientToServerMessage) => boolean
  setTranscriptContext: (context: TranscriptContext) => void
  addServerMessageListener: (
    listener: (message: ServerToClientMessage) => void,
  ) => () => void
}

const VoiceContext = createContext<VoiceContextValue | undefined>(undefined)

type VoiceProviderProps = {
  children: ReactNode
  socket?: WebSocket
}

<<<<<<< Updated upstream
// ── Provider ──────────────────────────────────────────────────────────────────

export function VoiceProvider({ children, socket = appSocket }: VoiceProviderProps) {
=======
export function VoiceProvider({ children, socket }: VoiceProviderProps) {
  const [resolvedSocket] = useState(() => socket ?? createAppSocket())
>>>>>>> Stashed changes
  const [transcript, setTranscript] = useState('')
  const [socketConnected, setSocketConnected] = useState(
    resolvedSocket.readyState === WebSocket.OPEN,
  )
  const lastSentRef = useRef<{ text: string; at: number }>({ text: '', at: 0 })
  const transcriptContextRef = useRef<TranscriptContext>({})
  const serverListenersRef = useRef(
    new Set<(message: ServerToClientMessage) => void>(),
  )
  const loopbackMode = import.meta.env.VITE_VOICE_LOCAL_LOOPBACK === 'true'

  // Stream state refs — which path is active for the current turn.
  const streamModeRef = useRef<'pcm' | 'accumulate' | null>(null)
  const streamResponseTextRef = useRef<string>('')
  const fallbackAccRef = useRef<FallbackAccumulator | null>(null)
  const agentResponseTextRef = useRef<string>('')
  const bargeInRecognitionRef = useRef<SpeechRecognition | null>(null)
  const bargeInEnabledRef = useRef(false)

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
<<<<<<< Updated upstream
    socket.addEventListener('open', onOpen)
    socket.addEventListener('close', onClose)
=======

    resolvedSocket.addEventListener('open', onOpen)
    resolvedSocket.addEventListener('close', onClose)

>>>>>>> Stashed changes
    return () => {
      resolvedSocket.removeEventListener('open', onOpen)
      resolvedSocket.removeEventListener('close', onClose)
      if (!socket) {
        resolvedSocket.close()
      }
    }
  }, [resolvedSocket, socket])

  const sendClientMessage = useCallback(
    (message: ClientToServerMessage) => {
      if (resolvedSocket.readyState !== WebSocket.OPEN) {
        return false
      }
      resolvedSocket.send(JSON.stringify(message))
      return true
    },
    [resolvedSocket],
  )

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
    (text: string, context: TranscriptContext = {}) => {
      const normalized = text.trim()
      if (!normalized) return false

      const now = Date.now()
      const duplicateSend =
        normalized === lastSentRef.current.text && now - lastSentRef.current.at < 1500
      if (duplicateSend) return false

      agentResponseTextRef.current = ''

<<<<<<< Updated upstream
      if (socket.readyState === WebSocket.OPEN) {
        const message: UserTranscriptMessage = { type: 'USER_TRANSCRIPT', text: normalized }
        socket.send(JSON.stringify(message))
=======
      const payload: UserTranscriptMessage = {
        type: 'USER_TRANSCRIPT',
        text: normalized,
        sessionId: context.sessionId ?? transcriptContextRef.current.sessionId,
        repoAgentId: context.repoAgentId ?? transcriptContextRef.current.repoAgentId,
        turnId: context.turnId ?? transcriptContextRef.current.turnId,
      }

      if (resolvedSocket.readyState === WebSocket.OPEN) {
        resolvedSocket.send(JSON.stringify(payload))
>>>>>>> Stashed changes
      } else if (loopbackMode) {
        const simulatedText = `You said: ${normalized}`
        agentResponseTextRef.current = simulatedText
        setTimeout(() => { void speak(simulatedText) }, 300)
      } else {
        return false
      }

      lastSentRef.current = { text: normalized, at: now }
      setTranscript('')
      return true
    },
    [loopbackMode, resolvedSocket, speak],
  )

  const setTranscriptContext = useCallback((context: TranscriptContext) => {
    transcriptContextRef.current = context
  }, [])

  const addServerMessageListener = useCallback(
    (listener: (message: ServerToClientMessage) => void) => {
      serverListenersRef.current.add(listener)
      return () => {
        serverListenersRef.current.delete(listener)
      }
    },
    [],
  )

  const { transcript: liveTranscript, isListening, startListening: startSTT, stopListening: stopSTT } =
    useSpeechToText({
      onFinalTranscript: (text) => {
        setTranscript(text)
        sendTranscript(text, transcriptContextRef.current)
      },
    })

  useEffect(() => {
    if (liveTranscript) setTranscript(liveTranscript)
  }, [liveTranscript])

  const stopBargeInMonitor = useCallback(() => {
    bargeInEnabledRef.current = false
    const recognition = bargeInRecognitionRef.current
    if (!recognition) {
      return
    }

    bargeInRecognitionRef.current = null
    try {
      recognition.abort()
    } catch {
      // Ignore browser errors while stopping.
    }
  }, [])

  const looksLikeAgentEcho = useCallback((spokenText: string) => {
    const normalizedSpoken = spokenText
      .toLowerCase()
      .replace(/[^\w\s]/g, ' ')
      .replace(/\s+/g, ' ')
      .trim()
    if (normalizedSpoken.length < 6) {
      return false
    }

    const normalizedAgent = agentResponseTextRef.current
      .toLowerCase()
      .replace(/[^\w\s]/g, ' ')
      .replace(/\s+/g, ' ')
      .trim()
    if (!normalizedAgent) {
      return false
    }

    const spokenWords = normalizedSpoken.split(' ').filter((word) => word.length > 1)
    if (spokenWords.length === 0) {
      return false
    }

    const overlappingWords = spokenWords.filter((word) => normalizedAgent.includes(word)).length
    return overlappingWords >= Math.max(2, Math.ceil(spokenWords.length * 0.7))
  }, [])

  const handleBargeInDetected = useCallback(
    (spokenText: string) => {
      if (!bargeInEnabledRef.current || looksLikeAgentEcho(spokenText)) {
        return
      }

      stopBargeInMonitor()
      stop()
      stopAudio()
      cleanupStream()
      startSTT()
    },
    [cleanupStream, looksLikeAgentEcho, startSTT, stop, stopAudio, stopBargeInMonitor],
  )

  const startBargeInMonitor = useCallback(() => {
    if (bargeInRecognitionRef.current || isListening) {
      return
    }

    const SpeechRecognitionCtor =
      window.SpeechRecognition ?? window.webkitSpeechRecognition
    if (!SpeechRecognitionCtor) {
      return
    }

    const recognition = new SpeechRecognitionCtor()
    recognition.continuous = true
    recognition.interimResults = true
    recognition.lang = 'en-US'
    bargeInEnabledRef.current = true

    recognition.onresult = (event: SpeechRecognitionEvent) => {
      if (!bargeInEnabledRef.current) {
        return
      }

      let heardText = ''
      for (let i = event.resultIndex; i < event.results.length; i += 1) {
        heardText += event.results[i][0]?.transcript ?? ''
      }

      const normalized = heardText.trim()
      const resultCount = event.results.length
      const latestResult = resultCount > 0 ? event.results[resultCount - 1] : null
      const isFinalResult = latestResult?.isFinal ?? false

      // Avoid interrupting on tiny interim snippets caused by noise/echo.
      const shouldInterrupt = isFinalResult ? normalized.length >= 2 : normalized.length >= 8
      if (shouldInterrupt) {
        handleBargeInDetected(normalized)
      }
    }

    recognition.onerror = () => {
      // Allow onend to restart while the agent is still speaking.
    }

    recognition.onend = () => {
      if (!bargeInEnabledRef.current) {
        bargeInRecognitionRef.current = null
        return
      }

      if (!isSpeaking && !isAudioPlaying) {
        bargeInEnabledRef.current = false
        bargeInRecognitionRef.current = null
        return
      }

      try {
        recognition.start()
      } catch {
        bargeInEnabledRef.current = false
        bargeInRecognitionRef.current = null
      }
    }

    bargeInRecognitionRef.current = recognition
    try {
      recognition.start()
    } catch {
      bargeInEnabledRef.current = false
      bargeInRecognitionRef.current = null
    }
  }, [handleBargeInDetected, isAudioPlaying, isListening, isSpeaking])

  useEffect(() => {
    const agentIsSpeaking = isSpeaking || isAudioPlaying
    if (agentIsSpeaking && !isListening) {
      startBargeInMonitor()
      return
    }

    stopBargeInMonitor()
  }, [isAudioPlaying, isListening, isSpeaking, startBargeInMonitor, stopBargeInMonitor])

  // ── WebSocket message handler ─────────────────────────────────────────────
  useEffect(() => {
    const onMessage = async (event: MessageEvent<string>) => {
      let payload: ServerToClientMessage
      try {
        payload = JSON.parse(event.data) as ServerToClientMessage
      } catch {
        return
      }

<<<<<<< Updated upstream
      // ── Legacy path: full audio blob in one message (AI_RESPONSE) ─────────
      // Unchanged from original behaviour; used as fallback when backend
      // does not support streaming.
      if (payload.type === 'AI_RESPONSE') {
        const message = payload as AIResponseMessage
        const responseText = message.responseText?.trim()
        if (!responseText) return

        agentResponseTextRef.current = responseText

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
=======
      serverListenersRef.current.forEach((listener) => {
        listener(payload)
      })

      if (payload.type !== 'AI_RESPONSE') {
>>>>>>> Stashed changes
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
        agentResponseTextRef.current = msg.responseText ?? ''

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

<<<<<<< Updated upstream
    socket.addEventListener('message', onMessage)
    return () => { socket.removeEventListener('message', onMessage) }
  }, [appendPcmChunk, cleanupStream, initPcmStream, playFromBase64, playFromUrl, socket, speak, stop, stopAudio])
=======
    resolvedSocket.addEventListener('message', onMessage)
    return () => {
      resolvedSocket.removeEventListener('message', onMessage)
    }
  }, [playFromBase64, playFromUrl, resolvedSocket, speak, stop])
>>>>>>> Stashed changes

  // ── Start / stop listening ────────────────────────────────────────────────
  const startListening = useCallback(() => {
    void unlock()

    // Barge-in: stop any ongoing playback and discard the current stream.
    if (isSpeaking || isAudioPlaying) {
      stopBargeInMonitor()
      stop()
      stopAudio()
    }
    cleanupStream()
    startSTT()
  }, [cleanupStream, isAudioPlaying, isSpeaking, startSTT, stop, stopAudio, stopBargeInMonitor, unlock])

  useEffect(() => () => {
    stopBargeInMonitor()
  }, [stopBargeInMonitor])

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
      sendClientMessage,
      setTranscriptContext,
      addServerMessageListener,
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
      sendClientMessage,
      setTranscriptContext,
      addServerMessageListener,
    ],
  )

  return <VoiceContext.Provider value={value}>{children}</VoiceContext.Provider>
}

export function useVoice(): VoiceContextValue {
  const context = useContext(VoiceContext)
  if (!context) throw new Error('useVoice must be used inside VoiceProvider')
  return context
}

