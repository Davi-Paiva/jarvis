import { useCallback, useEffect, useRef, useState } from 'react'

type UseSpeechToTextOptions = {
  onFinalTranscript: (text: string) => void
  lang?: string
}

type UseSpeechToTextReturn = {
  transcript: string
  finalTranscript: string
  isListening: boolean
  startListening: () => void
  stopListening: () => void
  isSupported: boolean
}

export function useSpeechToText({
  onFinalTranscript,
  lang = 'en-US',
}: UseSpeechToTextOptions): UseSpeechToTextReturn {
  const recognitionRef = useRef<SpeechRecognition | null>(null)
  const wantsListeningRef = useRef(false)
  const manualStopRef = useRef(false)
  const shouldRestartRef = useRef(false)
  const onFinalTranscriptRef = useRef(onFinalTranscript)

  const [transcript, setTranscript] = useState('')
  const [finalTranscript, setFinalTranscript] = useState('')
  const [isListening, setIsListening] = useState(false)
  const [isSupported, setIsSupported] = useState(true)

  useEffect(() => {
    onFinalTranscriptRef.current = onFinalTranscript
  }, [onFinalTranscript])

  useEffect(() => {
    const SpeechRecognitionCtor =
      window.SpeechRecognition ?? window.webkitSpeechRecognition

    if (!SpeechRecognitionCtor) {
      setIsSupported(false)
      return
    }

    const recognition = new SpeechRecognitionCtor()
    recognition.continuous = false
    recognition.interimResults = true
    recognition.lang = lang

    recognition.onstart = () => {
      setIsListening(true)
    }

    recognition.onresult = (event: SpeechRecognitionEvent) => {
      let interimText = ''
      let finalText = ''

      for (let i = event.resultIndex; i < event.results.length; i += 1) {
        const segment = event.results[i][0]?.transcript ?? ''
        if (event.results[i].isFinal) {
          finalText += segment
        } else {
          interimText += segment
        }
      }

      const liveText = (interimText || finalText).trim()
      setTranscript(liveText)

      const normalizedFinalText = finalText.trim()
      if (normalizedFinalText) {
        setFinalTranscript(normalizedFinalText)
        onFinalTranscriptRef.current(normalizedFinalText)
      }
    }

    recognition.onerror = () => {
      setIsListening(false)
      shouldRestartRef.current =
        wantsListeningRef.current && !manualStopRef.current
    }

    recognition.onend = () => {
      setIsListening(false)
      setTranscript('')

      if (shouldRestartRef.current) {
        shouldRestartRef.current = false
        try {
          recognition.start()
          return
        } catch {
          wantsListeningRef.current = false
        }
      }

      wantsListeningRef.current = false
      manualStopRef.current = false
    }

    recognitionRef.current = recognition

    return () => {
      manualStopRef.current = true
      wantsListeningRef.current = false
      shouldRestartRef.current = false
      recognition.abort()
    }
  }, [lang])

  const startListening = useCallback(() => {
    const recognition = recognitionRef.current
    if (!recognition) {
      return
    }

    manualStopRef.current = false
    wantsListeningRef.current = true
    shouldRestartRef.current = false
    setTranscript('')
    setFinalTranscript('')

    if (isListening) {
      return
    }

    try {
      recognition.start()
    } catch {
      // Ignore invalid-state errors while engine transitions.
    }
  }, [isListening])

  const stopListening = useCallback(() => {
    const recognition = recognitionRef.current
    if (!recognition) {
      return
    }

    manualStopRef.current = true
    wantsListeningRef.current = false
    shouldRestartRef.current = false
    recognition.stop()
  }, [])

  return {
    transcript,
    finalTranscript,
    isListening,
    startListening,
    stopListening,
    isSupported,
  }
}
