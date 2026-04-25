import '@testing-library/jest-dom/vitest'

class MockSpeechSynthesisUtterance {
  text: string
  onstart: (() => void) | null = null
  onend: (() => void) | null = null
  onerror: (() => void) | null = null

  constructor(text: string) {
    this.text = text
  }
}

Object.defineProperty(window, 'speechSynthesis', {
  value: {
    cancel: () => undefined,
    speak: (utterance: MockSpeechSynthesisUtterance) => {
      utterance.onstart?.()
      utterance.onend?.()
    },
  },
  configurable: true,
})

Object.defineProperty(window, 'SpeechSynthesisUtterance', {
  value: MockSpeechSynthesisUtterance,
  configurable: true,
})
