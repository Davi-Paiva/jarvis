import type {
  ClientToServerMessage,
  ServerToClientMessage,
  UserTranscriptMessage,
} from "../types/protocol";

export interface SessionWebSocketConfig {
  baseUrl?: string;
  onMessage?: (message: ServerToClientMessage) => void;
  onError?: (error: string) => void;
  onConnect?: () => void;
  onDisconnect?: () => void;
}

export interface TranscriptContext {
  sessionId?: string;
  repoAgentId?: string;
  turnId?: string;
}

export class SessionWebSocket {
  private ws: WebSocket | null = null;
  private config: SessionWebSocketConfig;
  private reconnectAttempts = 0;
  private maxReconnectAttempts = 5;
  private reconnectDelay = 1000;

  constructor(config: SessionWebSocketConfig) {
    this.config = {
      baseUrl: import.meta.env.VITE_API_BASE_URL || "http://localhost:8000",
      ...config,
    };
  }

  connect(): void {
    const wsUrl = this.config.baseUrl!
      .replace("http://", "ws://")
      .replace("https://", "wss://");
    const url = `${wsUrl}/ws`;

    try {
      this.ws = new WebSocket(url);

      this.ws.onopen = () => {
        this.reconnectAttempts = 0;
        this.reconnectDelay = 1000;
        this.config.onConnect?.();
      };

      this.ws.onmessage = (event) => {
        try {
          const message: ServerToClientMessage = JSON.parse(event.data);
          this.config.onMessage?.(message);
        } catch {
          this.config.onError?.("Failed to parse server message.");
        }
      };

      this.ws.onerror = () => {
        this.config.onError?.("WebSocket connection error");
      };

      this.ws.onclose = () => {
        this.config.onDisconnect?.();
        this.attemptReconnect();
      };
    } catch {
      this.config.onError?.("Failed to establish WebSocket connection");
    }
  }

  sendClientMessage(message: ClientToServerMessage): boolean {
    if (!this.isConnected()) {
      return false;
    }
    this.ws!.send(JSON.stringify(message));
    return true;
  }

  sendTranscript(text: string, context: TranscriptContext = {}): boolean {
    const payload: UserTranscriptMessage = {
      type: "USER_TRANSCRIPT",
      text,
      sessionId: context.sessionId,
      repoAgentId: context.repoAgentId,
      turnId: context.turnId,
    };
    return this.sendClientMessage(payload);
  }

  disconnect(): void {
    if (this.ws) {
      this.reconnectAttempts = this.maxReconnectAttempts;
      this.ws.close();
      this.ws = null;
    }
  }

  isConnected(): boolean {
    return this.ws !== null && this.ws.readyState === WebSocket.OPEN;
  }

  private attemptReconnect(): void {
    if (this.reconnectAttempts >= this.maxReconnectAttempts) {
      this.config.onError?.("Failed to reconnect to server");
      return;
    }

    this.reconnectAttempts += 1;
    window.setTimeout(() => this.connect(), this.reconnectDelay);
    this.reconnectDelay = Math.min(this.reconnectDelay * 2, 30000);
  }
}
