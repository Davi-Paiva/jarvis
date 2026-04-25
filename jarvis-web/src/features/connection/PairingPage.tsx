import { useState, useEffect, useRef, useCallback } from 'react'
import { motion, AnimatePresence } from 'framer-motion'

// ── Decryption title hook ─────────────────────────────────────────────────────
const CHARS = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789@#$%&'
const TARGET = 'JARVIS'
const SCRAMBLE_DURATION = 1800   // ms total
const SETTLE_INTERVAL   = 220    // ms between each letter settling

function useDecryptText(text: string) {
  const [display, setDisplay] = useState(() =>
    Array.from({ length: text.length }, () => CHARS[Math.floor(Math.random() * CHARS.length)]).join('')
  )
  const [settled, setSettled] = useState(0)

  useEffect(() => {
    let frame: number
    let settledCount = 0
    const startTime = performance.now()

    const tick = (now: number) => {
      const elapsed = now - startTime

      // Settle letters one by one
      const shouldSettle = Math.floor(elapsed / SETTLE_INTERVAL)
      if (shouldSettle > settledCount && settledCount < text.length) {
        settledCount = Math.min(shouldSettle, text.length)
        setSettled(settledCount)
      }

      setDisplay(
        text
          .split('')
          .map((char, i) =>
            i < settledCount
              ? char
              : CHARS[Math.floor(Math.random() * CHARS.length)]
          )
          .join('')
      )

      if (settledCount < text.length || elapsed < SCRAMBLE_DURATION) {
        frame = requestAnimationFrame(tick)
      } else {
        setDisplay(text)
        setSettled(text.length)
      }
    }

    frame = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(frame)
  }, [text])

  return { display, settled }
}

// ── Individual digit box ──────────────────────────────────────────────────────
type DigitBoxProps = {
  value: string
  focused: boolean
  shaking: boolean
  index: number
}

function DigitBox({ value, focused, shaking, index }: DigitBoxProps) {
  const glitch = {
    x: shaking ? [0, -3, 3, -2, 2, 0] : 0,
    y: shaking ? [0, 1, -1, 2, -2, 0] : 0,
    transition: shaking
      ? { duration: 0.35, times: [0, 0.2, 0.4, 0.6, 0.8, 1], delay: index * 0.04 }
      : {},
  }

  return (
    <motion.div
      animate={glitch}
      style={{
        width: 48,
        height: 60,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        fontFamily: "'JetBrains Mono', 'Fira Code', ui-monospace, monospace",
        fontSize: 26,
        fontWeight: 700,
        color: value ? '#00f2ff' : 'rgba(0,242,255,0.25)',
        background: 'rgba(0,242,255,0.03)',
        border: `1.5px solid ${focused ? 'rgba(0,242,255,0.9)' : shaking ? 'rgba(255,80,80,0.7)' : 'rgba(0,242,255,0.3)'}`,
        borderRadius: 6,
        boxShadow: focused
          ? '0 0 14px rgba(0,242,255,0.45), inset 0 0 8px rgba(0,242,255,0.08)'
          : shaking
          ? '0 0 12px rgba(255,80,80,0.4)'
          : '0 0 6px rgba(0,242,255,0.12)',
        transition: 'border-color 0.2s, box-shadow 0.2s',
        position: 'relative',
        userSelect: 'none',
      }}
    >
      {value || (focused ? <BlinkCursor /> : '')}
    </motion.div>
  )
}

function BlinkCursor() {
  return (
    <motion.span
      animate={{ opacity: [1, 0, 1] }}
      transition={{ duration: 1, repeat: Infinity, ease: 'linear' }}
      style={{ color: '#00f2ff', fontSize: 20 }}
    >
      |
    </motion.span>
  )
}

// ── Main PairingPage ──────────────────────────────────────────────────────────
type Props = {
  onConnect: (code: string) => void
}

export function PairingPage({ onConnect }: Props) {
  const { display, settled } = useDecryptText(TARGET)
  const [digits, setDigits] = useState(['', '', '', '', '', ''])
  const [focusIndex, setFocusIndex] = useState(0)
  const [shaking, setShaking] = useState(false)
  const [connecting, setConnecting] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)

  const code = digits.join('')
  const isFull = code.length === 6

  // Auto-connect attempt when 6th digit is entered
  useEffect(() => {
    if (!isFull) { setConnecting(false); return }
    setConnecting(true)
    const t = setTimeout(() => {
      // Delegate validation to parent — any 6-char code accepted here
      onConnect(code)
    }, 1200)
    return () => clearTimeout(t)
  }, [isFull, code, onConnect])

  const handleKey = useCallback((e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Backspace') {
      setConnecting(false)
      setDigits(prev => {
        const next = [...prev]
        const target = focusIndex > 0 && !prev[focusIndex] ? focusIndex - 1 : focusIndex
        next[target] = ''
        setFocusIndex(Math.max(0, target))
        return next
      })
      return
    }
    if (/^\d$/.test(e.key)) {
      const idx = focusIndex
      if (idx >= 6) return
      setDigits(prev => {
        const next = [...prev]
        next[idx] = e.key
        return next
      })
      setFocusIndex(Math.min(5, idx + 1))
    }
  }, [focusIndex])

  // Trigger glitch on wrong code (exposed via a shake if parent rejects)
  const triggerShake = useCallback(() => {
    setShaking(true)
    setConnecting(false)
    setTimeout(() => {
      setShaking(false)
      setDigits(['', '', '', '', '', ''])
      setFocusIndex(0)
      inputRef.current?.focus()
    }, 500)
  }, [])

  // Expose shake so parent can call it — we attach it to a data attribute
  // pattern to avoid prop drilling; parent calls window.__jarvisPairingShake?.()
  useEffect(() => {
    (window as Window & { __jarvisPairingShake?: () => void }).__jarvisPairingShake = triggerShake
    return () => { delete (window as Window & { __jarvisPairingShake?: () => void }).__jarvisPairingShake }
  }, [triggerShake])

  return (
    <div
      style={{
        position: 'fixed',
        inset: 0,
        background: '#00050a',
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        gap: 48,
        fontFamily: "'JetBrains Mono', 'Fira Code', ui-monospace, monospace",
        // Scanline overlay
        backgroundImage: `
          repeating-linear-gradient(
            0deg,
            rgba(0,0,0,0.18) 0px,
            rgba(0,0,0,0.18) 1px,
            transparent 1px,
            transparent 3px
          )
        `,
        overflow: 'hidden',
      }}
    >
      {/* Radial glow behind title */}
      <div style={{
        position: 'absolute',
        top: '28%',
        left: '50%',
        transform: 'translate(-50%, -50%)',
        width: 340,
        height: 200,
        background: 'radial-gradient(ellipse, rgba(0,242,255,0.09) 0%, transparent 70%)',
        pointerEvents: 'none',
      }} />

      {/* HUD corner brackets */}
      {(['tl','tr','bl','br'] as const).map(pos => (
        <div key={pos} style={{
          position: 'absolute',
          width: 22, height: 22,
          ...(pos.includes('t') ? { top: 16 } : { bottom: 16 }),
          ...(pos.includes('l') ? { left: 16 } : { right: 16 }),
          borderTop:    pos.includes('t') ? '1px solid rgba(0,242,255,0.4)' : 'none',
          borderBottom: pos.includes('b') ? '1px solid rgba(0,242,255,0.4)' : 'none',
          borderLeft:   pos.includes('l') ? '1px solid rgba(0,242,255,0.4)' : 'none',
          borderRight:  pos.includes('r') ? '1px solid rgba(0,242,255,0.4)' : 'none',
          pointerEvents: 'none',
        }} />
      ))}

      {/* ── Title ── */}
      <div style={{ textAlign: 'center', lineHeight: 1 }}>
        <div
          style={{
            fontSize: 64,
            fontWeight: 700,
            letterSpacing: '0.18em',
            color: '#00f2ff',
            textShadow: settled === TARGET.length
              ? '0 0 30px rgba(0,242,255,0.8), 0 0 60px rgba(0,242,255,0.35)'
              : '0 0 10px rgba(0,242,255,0.3)',
            transition: 'text-shadow 0.6s ease',
          }}
        >
          {display}
        </div>
        <div style={{
          marginTop: 10,
          fontSize: 11,
          letterSpacing: '0.28em',
          textTransform: 'uppercase',
          color: 'rgba(0,242,255,0.4)',
        }}>
          AI Control Interface
        </div>
      </div>

      {/* ── Digit boxes ── */}
      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 20 }}>
        <div style={{
          fontSize: 10,
          letterSpacing: '0.22em',
          textTransform: 'uppercase',
          color: 'rgba(0,242,255,0.35)',
          marginBottom: 4,
        }}>
          Enter Pairing Code
        </div>

        {/* Hidden real input for keyboard capture */}
        <input
          ref={inputRef}
          autoFocus
          inputMode="numeric"
          onKeyDown={handleKey}
          onFocus={() => {}}
          readOnly
          style={{ position: 'absolute', opacity: 0, pointerEvents: 'none', width: 1, height: 1 }}
          aria-label="Pairing code"
        />

        <div
          style={{ display: 'flex', gap: 10, cursor: 'text' }}
          onClick={() => inputRef.current?.focus()}
        >
          {digits.map((d, i) => (
            <DigitBox
              key={i}
              value={d}
              focused={focusIndex === i && !isFull}
              shaking={shaking}
              index={i}
            />
          ))}
        </div>

        {/* Separator dots */}
        <div style={{ display: 'flex', gap: 6 }}>
          {digits.map((d, i) => (
            <div key={i} style={{
              width: 4, height: 4, borderRadius: '50%',
              background: d ? '#00f2ff' : 'rgba(0,242,255,0.15)',
              boxShadow: d ? '0 0 6px #00f2ff' : 'none',
              transition: 'background 0.2s, box-shadow 0.2s',
            }} />
          ))}
        </div>
      </div>

      {/* ── Status line ── */}
      <div style={{ height: 32, display: 'flex', alignItems: 'center' }}>
        <AnimatePresence mode="wait">
          {connecting ? (
            <motion.div
              key="connecting"
              initial={{ opacity: 0, y: 6 }}
              animate={{ opacity: [0.5, 1, 0.5], y: 0 }}
              exit={{ opacity: 0, y: -6 }}
              transition={{ opacity: { duration: 1.1, repeat: Infinity, ease: 'easeInOut' }, y: { duration: 0.2 } }}
              style={{
                fontSize: 11,
                letterSpacing: '0.25em',
                textTransform: 'uppercase',
                color: '#00f2ff',
                textShadow: '0 0 10px rgba(0,242,255,0.6)',
              }}
            >
              ◈ &nbsp;Connecting...
            </motion.div>
          ) : (
            <motion.div
              key="hint"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              style={{
                fontSize: 11,
                letterSpacing: '0.18em',
                color: 'rgba(0,242,255,0.25)',
              }}
            >
              Find code in the Jarvis desktop app
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </div>
  )
}
