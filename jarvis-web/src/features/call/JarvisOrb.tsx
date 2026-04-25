import { useRef, useMemo } from 'react'
import { Canvas, useFrame } from '@react-three/fiber'
import { EffectComposer, Bloom } from '@react-three/postprocessing'
import * as THREE from 'three'

// ── Types ────────────────────────────────────────────────────────────────────
export type OrbCallState = 'inactive' | 'listening' | 'thinking' | 'responding'

type SceneProps = {
  callState: OrbCallState
  getVolume: () => number
}

// ── Helpers ──────────────────────────────────────────────────────────────────
function stateColor(callState: OrbCallState): string {
  return callState === 'listening' ? '#00ff88' : '#00f2ff'
}

// ── Core wireframe orb ───────────────────────────────────────────────────────
function OrbCore({ callState, getVolume }: SceneProps) {
  const meshRef = useRef<THREE.Mesh>(null!)
  const scaleRef = useRef(1)
  const color = stateColor(callState)

  useFrame((_, delta) => {
    meshRef.current.rotation.y += delta * 0.35
    meshRef.current.rotation.x += delta * 0.12

    const vol = getVolume()
    const isSpeaking = callState === 'responding'
    const target = isSpeaking ? 1 + vol * 1.1 : 1
    scaleRef.current += (target - scaleRef.current) * 0.18
    meshRef.current.scale.setScalar(scaleRef.current)
  })

  return (
    <mesh ref={meshRef}>
      <icosahedronGeometry args={[1, 1]} />
      <meshBasicMaterial wireframe color={color} transparent opacity={0.65} />
    </mesh>
  )
}

// ── Close particle cloud (orbits the orb) ────────────────────────────────────
function OrbCloud({ callState, getVolume }: SceneProps) {
  const ref = useRef<THREE.Points>(null!)
  const count = 320
  const color = stateColor(callState)

  const positions = useMemo(() => {
    const arr = new Float32Array(count * 3)
    for (let i = 0; i < count; i++) {
      const theta = Math.random() * Math.PI * 2
      const phi = Math.acos(2 * Math.random() - 1)
      const r = 1.35 + Math.random() * 0.3
      arr[i * 3]     = r * Math.sin(phi) * Math.cos(theta)
      arr[i * 3 + 1] = r * Math.sin(phi) * Math.sin(theta)
      arr[i * 3 + 2] = r * Math.cos(phi)
    }
    return arr
  }, [])

  useFrame((_, delta) => {
    ref.current.rotation.y -= delta * 0.06
    ref.current.rotation.x += delta * 0.03
    if (callState === 'responding') {
      ref.current.scale.setScalar(1 + getVolume() * 0.5)
    } else {
      ref.current.scale.setScalar(1)
    }
  })

  return (
    <points ref={ref}>
      <bufferGeometry>
        <bufferAttribute attach="attributes-position" args={[positions, 3]} />
      </bufferGeometry>
      <pointsMaterial size={0.018} color={color} transparent opacity={0.5} sizeAttenuation />
    </points>
  )
}

// ── Ambient field — fills the whole visible space ────────────────────────────
function AmbientField() {
  const ref = useRef<THREE.Points>(null!)
  const count = 1800

  const { positions, speeds } = useMemo(() => {
    const pos = new Float32Array(count * 3)
    const spd = new Float32Array(count)
    for (let i = 0; i < count; i++) {
      // scatter in a large cube, avoiding the orb centre (r > 2.5)
      let x: number, y: number, z: number
      do {
        x = (Math.random() - 0.5) * 28
        y = (Math.random() - 0.5) * 28
        z = (Math.random() - 0.5) * 18
      } while (Math.sqrt(x*x + y*y + z*z) < 2.5)
      pos[i * 3]     = x
      pos[i * 3 + 1] = y
      pos[i * 3 + 2] = z
      spd[i] = 0.003 + Math.random() * 0.006
    }
    return { positions: pos, speeds: spd }
  }, [])

  // Store mutable y-offsets in a ref so we don't trigger re-renders
  const driftRef = useRef(new Float32Array(count))

  useFrame((_, delta) => {
    // Very slow overall rotation
    ref.current.rotation.y += delta * 0.012
    ref.current.rotation.x += delta * 0.005

    // Individual particle drift (y-axis float)
    const geo = ref.current.geometry
    const attr = geo.attributes.position as THREE.BufferAttribute
    const arr = attr.array as Float32Array
    for (let i = 0; i < count; i++) {
      driftRef.current[i] += speeds[i] * delta * 60
      arr[i * 3 + 1] = positions[i * 3 + 1] + Math.sin(driftRef.current[i]) * 0.3
    }
    attr.needsUpdate = true
  })

  return (
    <points ref={ref}>
      <bufferGeometry>
        <bufferAttribute attach="attributes-position" args={[positions, 3]} />
      </bufferGeometry>
      <pointsMaterial
        size={0.025}
        color="#00d4ff"
        transparent
        opacity={0.18}
        sizeAttenuation
      />
    </points>
  )
}

// ── HUD ring ─────────────────────────────────────────────────────────────────
type RingProps = {
  radius: number
  speed: number
  opacity: number
  tilt?: [number, number, number]
}

function HudRing({ radius, speed, opacity, tilt = [0, 0, 0] }: RingProps) {
  const ref = useRef<THREE.Mesh>(null!)
  useFrame((_, delta) => { ref.current.rotation.z += delta * speed })
  return (
    <mesh ref={ref} rotation={tilt as [number, number, number]}>
      <torusGeometry args={[radius, 0.005, 3, 96]} />
      <meshBasicMaterial color="#00f2ff" transparent opacity={opacity} />
    </mesh>
  )
}

// ── Full scene ────────────────────────────────────────────────────────────────
function OrbScene({ callState, getVolume }: SceneProps) {
  return (
    <>
      <AmbientField />
      <OrbCore callState={callState} getVolume={getVolume} />
      <OrbCloud callState={callState} getVolume={getVolume} />
      <HudRing radius={1.75}  speed={0.4}   opacity={0.28} />
      <HudRing radius={2.05}  speed={-0.25} opacity={0.15} tilt={[Math.PI / 5, 0, 0]} />
      <EffectComposer>
        <Bloom intensity={1.8} luminanceThreshold={0.05} luminanceSmoothing={0.85} mipmapBlur />
      </EffectComposer>
    </>
  )
}

// ── Public component — full-screen canvas ────────────────────────────────────
type JarvisSceneProps = {
  callState: OrbCallState
  getVolume: () => number
}

export function JarvisOrb({ callState, getVolume }: JarvisSceneProps) {
  return (
    <Canvas
      camera={{ position: [0, 0, 6], fov: 55 }}
      gl={{ alpha: true, antialias: true }}
      style={{ position: 'absolute', inset: 0, width: '100%', height: '100%' }}
    >
      <OrbScene callState={callState} getVolume={getVolume} />
    </Canvas>
  )
}

