import { VoiceButton } from './voice/components/VoiceButton.tsx'
import { useVoice } from './voice/context/VoiceProvider.tsx'
import './App.css'

function App() {
  const { transcript, listening, speaking, socketConnected, loopbackMode } = useVoice()

  return (
    <main className="voice-page">
      <section className="voice-card" aria-live="polite">
        <header>
          <p className="eyebrow">Jarvis Voice</p>
          <h1>Talk naturally.</h1>
          <p className="status-badges">
            <span className={`badge ${socketConnected ? 'ok' : 'warn'}`}>
              {socketConnected ? 'Socket connected' : 'Socket disconnected'}
            </span>
            {loopbackMode ? <span className="badge info">Loopback test mode</span> : null}
          </p>
          <p className="status-line">
            {listening
              ? 'Listening...'
              : speaking
                ? 'Jarvis is speaking...'
                : 'Tap the button to start a voice turn.'}
          </p>
        </header>

        <div className="transcript-wrap">
          <p className="transcript-label">Live Transcript</p>
          <p className="transcript-text">
            {transcript || 'Your words will appear here as you speak.'}
          </p>
        </div>

        <VoiceButton />
      </section>
    </main>
  )
}

export default App
