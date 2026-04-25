/**
 * WebSocket client for real-time chat communication with the backend.
 */

export type MessageRole = 'user' | 'assistant' | 'system';

export interface ChatMessage {
  role: MessageRole;
  content: string;
  timestamp?: string;
  messageId?: string;
}

export interface StreamToken {
  type: 'token';
  content: string;
  index: number;
}

export interface StreamStart {
  type: 'start';
  message_id: string;
}

export interface StreamEnd {
  type: 'end';
  message_id: string;
  content: string;
}

export interface ErrorMessage {
  type: 'error';
  content: string;
}

export interface ConnectionMessage {
  type: 'connected';
  repo_id: string;
  message: string;
}

export type WebSocketMessage = 
  | StreamToken 
  | StreamStart 
  | StreamEnd 
  | ErrorMessage 
  | ConnectionMessage
  | { type: 'pong' };

export interface ChatWebSocketConfig {
  repoId: string;
  clientId: string;
  baseUrl?: string;
  onMessage?: (message: WebSocketMessage) => void;
  onToken?: (token: string) => void;
  onComplete?: (fullMessage: string) => void;
  onError?: (error: string) => void;
  onConnect?: () => void;
  onDisconnect?: () => void;
}

export class ChatWebSocket {
  private ws: WebSocket | null = null;
  private config: ChatWebSocketConfig;
  private reconnectAttempts = 0;
  private maxReconnectAttempts = 5;
  private reconnectDelay = 1000; // Start with 1 second
  private currentMessageBuffer = '';
  
  constructor(config: ChatWebSocketConfig) {
    this.config = {
      baseUrl: import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000',
      ...config
    };
  }
  
  /**
   * Connect to the WebSocket server
   */
  connect(): void {
    const wsUrl = this.config.baseUrl!
      .replace('http://', 'ws://')
      .replace('https://', 'wss://');
    
    const url = `${wsUrl}/ws/chat/${this.config.repoId}/${this.config.clientId}`;
    
    try {
      this.ws = new WebSocket(url);
      
      this.ws.onopen = () => {
        this.reconnectAttempts = 0;
        this.reconnectDelay = 1000;
        this.config.onConnect?.();
      };
      
      this.ws.onmessage = (event) => {
        try {
          const message: WebSocketMessage = JSON.parse(event.data);
          this.handleMessage(message);
        } catch (error) {
          console.error('[WebSocket] Failed to parse message:', error);
        }
      };
      
      this.ws.onerror = () => {
        this.config.onError?.('WebSocket connection error');
      };
      
      this.ws.onclose = () => {
        this.config.onDisconnect?.();
        this.attemptReconnect();
      };
    } catch (error) {
      console.error('[WebSocket] Failed to create connection:', error);
      this.config.onError?.('Failed to establish WebSocket connection');
    }
  }
  
  /**
   * Handle incoming WebSocket messages
   */
  private handleMessage(message: WebSocketMessage): void {
    this.config.onMessage?.(message);
    
    switch (message.type) {
      case 'connected':
        break;
        
      case 'start':
        this.currentMessageBuffer = '';
        break;
        
      case 'token':
        this.currentMessageBuffer += message.content;
        this.config.onToken?.(message.content);
        break;
        
      case 'end':
        // Use message.content from the end event
        const endContent = message.content || '';
        this.config.onComplete?.(endContent);
        this.currentMessageBuffer = '';
        break;
        
      case 'error':
        this.config.onError?.(message.content);
        break;
        
      case 'pong':
        break;
        
      default:
        console.warn('[WebSocket] Unknown message type:', message);
    }
  }
  
  /**
   * Send a chat message
   */
  sendMessage(content: string, threadId?: string): void {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
      this.config.onError?.('WebSocket is not connected');
      return;
    }
    
    const message = {
      type: 'message',
      content,
      thread_id: threadId
    };
    
    this.ws.send(JSON.stringify(message));
  }
  
  /**
   * Send a ping to keep connection alive
   */
  ping(): void {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({ type: 'ping' }));
    }
  }
  
  /**
   * Attempt to reconnect with exponential backoff
   */
  private attemptReconnect(): void {
    if (this.reconnectAttempts >= this.maxReconnectAttempts) {
      console.error('[WebSocket] Max reconnect attempts reached');
      this.config.onError?.('Failed to reconnect to server');
      return;
    }
    
    this.reconnectAttempts++;
    console.log(`[WebSocket] Reconnecting in ${this.reconnectDelay}ms (attempt ${this.reconnectAttempts})`);
    
    setTimeout(() => {
      this.connect();
    }, this.reconnectDelay);
    
    // Exponential backoff
    this.reconnectDelay = Math.min(this.reconnectDelay * 2, 30000); // Max 30 seconds
  }
  
  /**
   * Disconnect from the WebSocket server
   */
  disconnect(): void {
    if (this.ws) {
      this.reconnectAttempts = this.maxReconnectAttempts; // Prevent auto-reconnect
      this.ws.close();
      this.ws = null;
    }
  }
  
  /**
   * Check if connected
   */
  isConnected(): boolean {
    return this.ws !== null && this.ws.readyState === WebSocket.OPEN;
  }
}
