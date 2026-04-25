export const defaultSocketUrl =
  import.meta.env.VITE_WS_URL ?? 'ws://localhost:8000/ws'

export function createAppSocket(url: string = defaultSocketUrl): WebSocket {
  return new WebSocket(url)
}
