import { useCallback, useEffect, useRef, useState } from 'react'

type UseAudioPlaybackReturn = {
  unlock: () => Promise<void>
  playFromUrl: (audioUrl: string) => Promise<boolean>
  playFromBase64: (audioBase64: string, mimeType?: string) => Promise<boolean>
  stop: () => void
  isPlaying: boolean
  getVolume: () => number
}

function base64ToBlob(base64: string, mimeType: string): Blob {
  const binary = atob(base64)
  const len = binary.length
  const bytes = new Uint8Array(len)

  for (let i = 0; i < len; i += 1) {
    bytes[i] = binary.charCodeAt(i)
  }

  return new Blob([bytes], { type: mimeType })
}

export function useAudioPlayback(): UseAudioPlaybackReturn {
  const audioRef = useRef<HTMLAudioElement | null>(null)
  const audioContextRef = useRef<AudioContext | null>(null)
  const analyserRef = useRef<AnalyserNode | null>(null)
  const freqDataRef = useRef<Uint8Array>(new Uint8Array(0))
  const sourceRef = useRef<AudioBufferSourceNode | null>(null)
  const objectUrlRef = useRef<string | null>(null)
  const [isPlaying, setIsPlaying] = useState(false)

  const getAudioContext = useCallback(() => {
    if (audioContextRef.current) {
      return audioContextRef.current
    }

    const Ctx = window.AudioContext || (window as typeof window & { webkitAudioContext?: typeof AudioContext }).webkitAudioContext
    if (!Ctx) {
      return null
    }

    const ctx = new Ctx()
    const analyser = ctx.createAnalyser()
    analyser.fftSize = 256
    analyser.smoothingTimeConstant = 0.8
    analyser.connect(ctx.destination)
    analyserRef.current = analyser
    freqDataRef.current = new Uint8Array(analyser.frequencyBinCount)
    audioContextRef.current = ctx
    return ctx
  }, [])

  const unlock = useCallback(async () => {
    const context = getAudioContext()
    if (!context) {
      return
    }

    if (context.state === 'suspended') {
      await context.resume()
    }

    // Prime the output with a one-sample silent buffer in a user gesture path.
    const buffer = context.createBuffer(1, 1, context.sampleRate)
    const source = context.createBufferSource()
    source.buffer = buffer
    source.connect(context.destination)
    source.start(0)
  }, [getAudioContext])

  const clearObjectUrl = useCallback(() => {
    if (objectUrlRef.current) {
      URL.revokeObjectURL(objectUrlRef.current)
      objectUrlRef.current = null
    }
  }, [])

  const stop = useCallback(() => {
    if (audioRef.current) {
      audioRef.current.pause()
      audioRef.current.currentTime = 0
      audioRef.current = null
    }

    if (sourceRef.current) {
      sourceRef.current.stop()
      sourceRef.current.disconnect()
      sourceRef.current = null
    }

    clearObjectUrl()
    setIsPlaying(false)
  }, [clearObjectUrl])

  useEffect(() => {
    return () => {
      stop()
    }
  }, [stop])

  const playFromUrl = useCallback(
    async (audioUrl: string) => {
      const src = audioUrl.trim()
      if (!src) {
        return false
      }

      stop()
      const audio = new Audio(src)
      audio.crossOrigin = 'anonymous'
      audioRef.current = audio

      // Tap into Web Audio analyser if available
      const context = getAudioContext()
      if (context && analyserRef.current) {
        try {
          const mediaSource = context.createMediaElementSource(audio)
          mediaSource.connect(analyserRef.current)
        } catch {
          // ignore – element may already be connected
        }
      }

      const played = await new Promise<boolean>((resolve) => {
        audio.onplaying = () => {
          setIsPlaying(true)
        }

        const finish = (success: boolean) => {
          setIsPlaying(false)
          audioRef.current = null
          resolve(success)
        }

        audio.onended = () => finish(true)
        audio.onerror = () => finish(false)
        void audio.play().catch(() => finish(false))
      })

      return played
    },
    [getAudioContext, stop],
  )

  const playFromBase64 = useCallback(
    async (audioBase64: string, mimeType = 'audio/mpeg') => {
      const normalized = audioBase64.trim()
      if (!normalized) {
        return false
      }

      stop()

      const context = getAudioContext()
      if (!context) {
        const blob = base64ToBlob(normalized, mimeType)
        const objectUrl = URL.createObjectURL(blob)
        objectUrlRef.current = objectUrl
        const played = await playFromUrl(objectUrl)
        clearObjectUrl()
        return played
      }

      try {
        if (context.state === 'suspended') {
          await context.resume()
        }

        const blob = base64ToBlob(normalized, mimeType)
        const arrayBuffer = await blob.arrayBuffer()
        const decoded = await context.decodeAudioData(arrayBuffer)
        const source = context.createBufferSource()
        source.buffer = decoded
        source.connect(analyserRef.current ?? context.destination)
        if (analyserRef.current) {
          // analyser already connected to destination; don't double-connect
        } else {
          source.connect(context.destination)
        }
        sourceRef.current = source

        const played = await new Promise<boolean>((resolve) => {
          setIsPlaying(true)
          source.onended = () => {
            if (sourceRef.current === source) {
              sourceRef.current = null
            }
            setIsPlaying(false)
            resolve(true)
          }

          try {
            source.start(0)
          } catch {
            setIsPlaying(false)
            resolve(false)
          }
        })

        return played
      } catch {
        return false
      }
    },
    [clearObjectUrl, getAudioContext, playFromUrl, stop],
  )

  const getVolume = useCallback((): number => {
    const analyser = analyserRef.current
    const data = freqDataRef.current
    if (!analyser || data.length === 0) return 0
    analyser.getByteFrequencyData(data as Uint8Array<ArrayBuffer>)
    let sum = 0
    for (let i = 0; i < data.length; i++) sum += data[i]
    return sum / (data.length * 255)
  }, [])

  return { unlock, playFromUrl, playFromBase64, stop, isPlaying, getVolume }
}
