declare global {
  interface Window {
    webkitSpeechRecognition?: SpeechRecognitionStatic
    SpeechRecognition?: SpeechRecognitionStatic
  }

  interface SpeechRecognitionStatic {
    new (): SpeechRecognition
  }

  interface SpeechRecognition extends EventTarget {
    continuous: boolean
    interimResults: boolean
    lang: string
    onstart: ((this: SpeechRecognition, event: Event) => void) | null
    onresult:
      | ((this: SpeechRecognition, event: SpeechRecognitionEvent) => void)
      | null
    onerror: ((this: SpeechRecognition, event: Event) => void) | null
    onend: ((this: SpeechRecognition, event: Event) => void) | null
    start: () => void
    stop: () => void
    abort: () => void
  }

  interface SpeechRecognitionEvent extends Event {
    resultIndex: number
    results: SpeechRecognitionResultList
  }

  interface SpeechRecognitionResultList {
    [index: number]: SpeechRecognitionResult
    length: number
  }

  interface SpeechRecognitionResult {
    [index: number]: SpeechRecognitionAlternative
    isFinal: boolean
    length: number
  }

  interface SpeechRecognitionAlternative {
    transcript: string
    confidence: number
  }
}

export {}
