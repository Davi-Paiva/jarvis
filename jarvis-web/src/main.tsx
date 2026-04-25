import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'
import { VoiceProvider } from './voice/context/VoiceProvider.tsx'

// Suppress THREE.Clock deprecation — emitted by @react-three/fiber internals,
// not our code. Remove once r3f upgrades to THREE.Timer.
const _warn = console.warn.bind(console)
console.warn = (...args: unknown[]) => {
  if (typeof args[0] === 'string' && args[0].includes('THREE.Clock')) return
  _warn(...args)
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <VoiceProvider>
      <App />
    </VoiceProvider>
  </StrictMode>,
)
