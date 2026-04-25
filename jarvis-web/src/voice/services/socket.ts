const socketUrl = import.meta.env.VITE_WS_URL ?? 'ws://localhost:8000/ws'

export const appSocket = new WebSocket(socketUrl)
