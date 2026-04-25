import { useCallback, useEffect, useState } from 'react'

type UseTextToSpeechReturn = {
  speak: (text: string) => Promise<void>
  stop: () => void
  isSpeaking: boolean
}

export function useTextToSpeech(): UseTextToSpeechReturn {
  const [isSpeaking, setIsSpeaking] = useState(false)

  useEffect(() => {
    return () => {
      window.speechSynthesis.cancel()
    }
  }, [])

  const stop = useCallback(() => {
    window.speechSynthesis.cancel()
    setIsSpeaking(false)
  }, [])

  const speak = useCallback((text: string) => {
    const normalizedText = text.trim()
    if (!normalizedText) {
      return Promise.resolve()
    }

    window.speechSynthesis.cancel()

    return new Promise<void>((resolve) => {
      const utterance = new SpeechSynthesisUtterance(normalizedText)

      utterance.onstart = () => {
        setIsSpeaking(true)
      }

      const finish = () => {
        setIsSpeaking(false)
        resolve()
      }

      utterance.onend = finish
      utterance.onerror = finish
      window.speechSynthesis.speak(utterance)
    })
  }, [])

  return { speak, stop, isSpeaking }
}
