import { useVoice } from '../context/VoiceProvider.tsx'

export function VoiceButton() {
  const { listening, startListening, stopListening } = useVoice()

  const toggleListening = () => {
    if (listening) {
      stopListening()
      return
    }

    startListening()
  }

  return (
    <button
      type="button"
      className={`voice-button ${listening ? 'listening' : ''}`}
      onClick={toggleListening}
      aria-pressed={listening}
      aria-label={listening ? 'Stop listening' : 'Start listening'}
    >
      {listening ? 'Stop Listening' : 'Start Listening'}
    </button>
  )
}
