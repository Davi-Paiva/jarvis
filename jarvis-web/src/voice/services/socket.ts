export const defaultSocketUrl =
  import.meta.env.VITE_WS_URL ?? 'ws://localhost:8000/ws'

let appSocket: WebSocket | null = null

export function createAppSocket(url: string = defaultSocketUrl): WebSocket {
  return new WebSocket(url)
}

export function getAppSocket(url: string = defaultSocketUrl): WebSocket {
  if (
    !appSocket ||
    appSocket.readyState === WebSocket.CLOSING ||
    appSocket.readyState === WebSocket.CLOSED
  ) {
    appSocket = createAppSocket(url)
  }
  return appSocket
}
