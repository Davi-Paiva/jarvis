import { useState, useEffect, useRef } from "react";
import { open } from "@tauri-apps/plugin-dialog";
import { ChatWebSocket } from "../services/websocket";
import "./MainPage.css";

interface Folder {
  id: string;
  name: string;
  path: string;
  repoId?: string; // Backend repo ID
}

interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  timestamp: Date;
}

interface MainPageProps {
  initialFolder: string;
  repoId?: string; // Backend repo ID from folder activation
}

function MainPage({ initialFolder, repoId }: MainPageProps) {
  const [folders, setFolders] = useState<Folder[]>([
    {
      id: "1",
      name: initialFolder.split("/").pop() || "Project",
      path: initialFolder,
      repoId: repoId,
    },
  ]);
  const [selectedFolderId, setSelectedFolderId] = useState<string>("1");
  const [messages, setMessages] = useState<Message[]>([
    {
      id: "1",
      role: "assistant",
      content: "Hello! I'm JARVIS, your AI development assistant. How can I help you with your project today?",
      timestamp: new Date(),
    },
  ]);
  const [inputMessage, setInputMessage] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [isConnected, setIsConnected] = useState(false);
  const [streamingMessageId, setStreamingMessageId] = useState<string | null>(null);
  
  const wsRef = useRef<ChatWebSocket | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  // Auto-scroll to bottom when new messages arrive
  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  // Connect to WebSocket when component mounts with a repoId
  useEffect(() => {
    if (!repoId) {
      console.log('[MainPage] No repoId provided, skipping WebSocket connection');
      return;
    }

    console.log('[MainPage] Connecting to WebSocket with repoId:', repoId);
    
    const clientId = `client-${Date.now()}`;
    
    const ws = new ChatWebSocket({
      repoId: repoId,
      clientId,
      onConnect: () => {
        console.log('[MainPage] ✓ WebSocket connected');
        setIsConnected(true);
      },
      onDisconnect: () => {
        console.log('[MainPage] ✗ WebSocket disconnected');
        setIsConnected(false);
      },
      onToken: (token: string) => {
        setMessages((prev) => {
          const lastMessage = prev[prev.length - 1];
          if (lastMessage && lastMessage.id === streamingMessageId) {
            return [
              ...prev.slice(0, -1),
              { ...lastMessage, content: lastMessage.content + token },
            ];
          }
          return prev;
        });
      },
      onComplete: (fullMessage: string) => {
        console.log('[MainPage] Message complete:', fullMessage);
        setIsLoading(false);
        setStreamingMessageId(null);
      },
      onError: (error: string) => {
        console.error('[MainPage] WebSocket error:', error);
        setIsLoading(false);
        setStreamingMessageId(null);
        
        const errorMessage: Message = {
          id: `error-${Date.now()}`,
          role: "assistant",
          content: `Error: ${error}`,
          timestamp: new Date(),
        };
        setMessages((prev) => [...prev, errorMessage]);
      },
    });

    ws.connect();
    wsRef.current = ws;

    // Cleanup on unmount
    return () => {
      console.log('[MainPage] Cleaning up WebSocket connection');
      ws.disconnect();
      wsRef.current = null;
    };
  }, [repoId]); // Only reconnect if repoId changes

  const handleAddFolder = async () => {
    try {
      const selected = await open({
        directory: true,
        multiple: false,
        title: "Select Project Folder",
      });

      if (selected && typeof selected === "string") {
        const newFolder: Folder = {
          id: Date.now().toString(),
          name: selected.split("/").pop() || "Project",
          path: selected,
        };
        setFolders([...folders, newFolder]);
        setSelectedFolderId(newFolder.id);
      }
    } catch (error) {
      console.error("Error selecting folder:", error);
    }
  };

  const handleSendMessage = () => {
    console.log('[MainPage] handleSendMessage called, inputMessage:', inputMessage);
    
    if (!inputMessage.trim()) {
      console.log('[MainPage] Empty message, ignoring');
      return;
    }

    // Check if WebSocket is connected
    console.log('[MainPage] Checking WebSocket - wsRef:', !!wsRef.current, 'isConnected:', isConnected);
    
    if (!wsRef.current || !isConnected) {
      console.error('[MainPage] WebSocket not connected!');
      const errorMessage: Message = {
        id: `error-${Date.now()}`,
        role: "assistant",
        content: "Not connected to server. Please wait for connection or restart the backend.",
        timestamp: new Date(),
      };
      setMessages((prev) => [...prev, errorMessage]);
      return;
    }

    console.log('[MainPage] Creating user message');
    const newMessage: Message = {
      id: Date.now().toString(),
      role: "user",
      content: inputMessage,
      timestamp: new Date(),
    };

    setMessages((prev) => [...prev, newMessage]);
    setInputMessage("");
    setIsLoading(true);

    // Create placeholder for assistant's streaming response
    const assistantMessageId = `assistant-${Date.now()}`;
    const assistantMessage: Message = {
      id: assistantMessageId,
      role: "assistant",
      content: "",
      timestamp: new Date(),
    };
    
    setMessages((prev) => [...prev, assistantMessage]);
    setStreamingMessageId(assistantMessageId);

    // Send message via WebSocket
    console.log('[MainPage] Calling wsRef.current.sendMessage()');
    wsRef.current.sendMessage(inputMessage);
    console.log('[MainPage] sendMessage call completed');
  };

  const handleKeyPress = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSendMessage();
    }
  };

  const selectedFolder = folders.find((f) => f.id === selectedFolderId);

  return (
    <div className="main-page">
      {/* Sidebar */}
      <aside className="sidebar">
        <div className="sidebar-header">
          <h2 className="sidebar-title">Workspaces</h2>
        </div>

        <div className="folders-list">
          {folders.map((folder) => (
            <button
              key={folder.id}
              className={`folder-item ${
                selectedFolderId === folder.id ? "active" : ""
              }`}
              onClick={() => setSelectedFolderId(folder.id)}
            >
              <svg
                className="folder-icon-small"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
              >
                <path d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z" />
              </svg>
              <span className="folder-name">{folder.name}</span>
            </button>
          ))}
        </div>

        <button className="add-folder-button" onClick={handleAddFolder}>
          <svg
            width="16"
            height="16"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
          >
            <line x1="12" y1="5" x2="12" y2="19" />
            <line x1="5" y1="12" x2="19" y2="12" />
          </svg>
          Add Folder
        </button>
      </aside>

      {/* Chat Area */}
      <div className="chat-container">
        <div className="chat-header">
          <div className="chat-header-info">
            <h3 className="chat-title">{selectedFolder?.name}</h3>
            <p className="chat-subtitle">{selectedFolder?.path}</p>
          </div>
          {repoId && (
            <div className={`connection-status ${isConnected ? 'connected' : 'disconnected'}`}>
              <span className="status-dot"></span>
              {isConnected ? 'Connected' : 'Disconnected'}
            </div>
          )}
        </div>

        <div className="messages-container">
          {messages.map((message) => (
            <div
              key={message.id}
              className={`message ${message.role === "user" ? "user-message" : "assistant-message"}`}
            >
              <div className="message-avatar">
                {message.role === "user" ? (
                  <svg
                    viewBox="0 0 24 24"
                    fill="currentColor"
                    width="20"
                    height="20"
                  >
                    <path d="M12 12c2.21 0 4-1.79 4-4s-1.79-4-4-4-4 1.79-4 4 1.79 4 4 4zm0 2c-2.67 0-8 1.34-8 4v2h16v-2c0-2.66-5.33-4-8-4z" />
                  </svg>
                ) : (
                  <span className="assistant-avatar">J</span>
                )}
              </div>
              <div className="message-content">
                <div className="message-text">{message.content}</div>
              </div>
            </div>
          ))}
          {isLoading && (
            <div className="message assistant-message">
              <div className="message-avatar">
                <span className="assistant-avatar">J</span>
              </div>
              <div className="message-content">
                <div className="typing-indicator">
                  <span></span>
                  <span></span>
                  <span></span>
                </div>
              </div>
            </div>
          )}
          <div ref={messagesEndRef} />
        </div>

        <div className="input-container">
          <textarea
            className="message-input"
            placeholder="Ask JARVIS anything about your code..."
            value={inputMessage}
            onChange={(e) => setInputMessage(e.target.value)}
            onKeyPress={handleKeyPress}
            rows={1}
          />
          <button
            className="send-button"
            onClick={handleSendMessage}
            disabled={!inputMessage.trim() || isLoading}
          >
            <svg
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <line x1="22" y1="2" x2="11" y2="13" />
              <polygon points="22 2 15 22 11 13 2 9 22 2" />
            </svg>
          </button>
        </div>
      </div>
    </div>
  );
}

export default MainPage;
