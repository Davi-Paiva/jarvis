import { useEffect, useMemo, useRef, useState, type Dispatch, type SetStateAction } from "react";
import { open } from "@tauri-apps/plugin-dialog";
import { apiService } from "../services/api";
import { SessionWebSocket } from "../services/websocket";
import type {
  PendingTurnMessage,
  PendingTurnSummary,
  RepoSummary,
  ServerToClientMessage,
  SessionStateMessage,
  VoiceChatMessage,
} from "../types/protocol";
import "./MainPage.css";

interface Folder {
  id: string;
  name: string;
  path: string;
  repoAgentId?: string;
}

interface Message {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
  timestamp: Date;
  turnId?: string;
}

interface MainPageProps {
  initialFolder: string;
  initialRepoAgentId?: string;
}

function MainPage({ initialFolder, initialRepoAgentId }: MainPageProps) {
  const [folders, setFolders] = useState<Folder[]>([
    {
      id: "1",
      name: initialFolder.split("/").pop() || "Project",
      path: initialFolder,
      repoAgentId: initialRepoAgentId,
    },
  ]);
  const [selectedFolderId, setSelectedFolderId] = useState<string>("1");
  const [messagesByRepo, setMessagesByRepo] = useState<Record<string, Message[]>>({});
  const [pendingTurns, setPendingTurns] = useState<PendingTurnSummary[]>([]);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [activeRepoAgentId, setActiveRepoAgentId] = useState<string | null>(
    initialRepoAgentId || null,
  );
  const [inputMessage, setInputMessage] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [loadingStatus, setLoadingStatus] = useState("JARVIS is processing your message...");
  const [isConnected, setIsConnected] = useState(false);

  const wsRef = useRef<SessionWebSocket | null>(null);
  const selectedRepoAgentIdRef = useRef<string | undefined>(initialRepoAgentId);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const selectedFolder = useMemo(
    () => folders.find((folder) => folder.id === selectedFolderId),
    [folders, selectedFolderId],
  );
  const selectedRepoAgentId = selectedFolder?.repoAgentId;
  const selectedPendingTurn = useMemo(
    () =>
      pendingTurns.find(
        (turn) => turn.repoAgentId === selectedRepoAgentId && turn.requiresUserResponse,
      ),
    [pendingTurns, selectedRepoAgentId],
  );
  const selectedMessages = selectedRepoAgentId
    ? messagesByRepo[selectedRepoAgentId] || []
    : [];

  useEffect(() => {
    selectedRepoAgentIdRef.current = selectedRepoAgentId;
  }, [selectedRepoAgentId]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [selectedMessages, isLoading]);

  useEffect(() => {
    const ws = new SessionWebSocket({
      onConnect: () => {
        setIsConnected(true);
        ws.sendClientMessage({
          type: "SESSION_START",
          sessionId: undefined,
        });
      },
      onDisconnect: () => {
        setIsConnected(false);
      },
      onMessage: (message) => {
        handleServerMessage(
          message,
          setSessionId,
          setActiveRepoAgentId,
          setPendingTurns,
          setFolders,
          setMessagesByRepo,
          setIsLoading,
        );
      },
      onError: (error) => {
        setIsLoading(false);
        appendLocalMessage(
          setMessagesByRepo,
          selectedRepoAgentIdRef.current,
          "system",
          `Error: ${error}`,
        );
      },
    });

    ws.connect();
    wsRef.current = ws;

    return () => {
      ws.disconnect();
      wsRef.current = null;
    };
  }, []);

  const handleAddFolder = async () => {
    try {
      const selected = await open({
        directory: true,
        multiple: false,
        title: "Select Project Folder",
      });

      if (!selected || typeof selected !== "string") {
        return;
      }

      const folderName = selected.split("/").pop() || "Project";
      const result = await apiService.activateFolder(selected, folderName);
      const nextFolder: Folder = {
        id: `folder-${result.repo_agent_id}`,
        name: folderName,
        path: selected,
        repoAgentId: result.repo_agent_id,
      };

      setFolders((prev) => upsertFolder(prev, nextFolder));
      setSelectedFolderId(`folder-${result.repo_agent_id}`);
    } catch (error) {
      const detail =
        typeof error === "object" && error && "detail" in error
          ? String((error as { detail: string }).detail)
          : "Failed to activate folder.";
      appendLocalMessage(setMessagesByRepo, selectedRepoAgentId, "system", detail);
    }
  };

  const handleSendMessage = () => {
    const text = inputMessage.trim();
    if (!text) {
      return;
    }

    if (!selectedRepoAgentId) {
      appendLocalMessage(
        setMessagesByRepo,
        selectedRepoAgentId,
        "system",
        "Select or activate a workspace before sending a message.",
      );
      return;
    }

    if (!wsRef.current || !isConnected) {
      appendLocalMessage(
        setMessagesByRepo,
        selectedRepoAgentId,
        "system",
        "Not connected to the backend. Please wait for reconnection.",
      );
      return;
    }

    const looksLikeExecutionApproval =
      isApproval(text) &&
      !!selectedPendingTurn &&
      selectedPendingTurn.type === "EXECUTION_APPROVAL";

    setLoadingStatus(
      looksLikeExecutionApproval
        ? "Executing approved plan..."
        : "JARVIS is processing your message...",
    );
    setInputMessage("");
    setIsLoading(true);

    const sent = wsRef.current.sendTranscript(text, {
      sessionId: sessionId || undefined,
      repoAgentId: selectedRepoAgentId,
      turnId: selectedPendingTurn?.turnId,
    });

    if (!sent) {
      setIsLoading(false);
      appendLocalMessage(
        setMessagesByRepo,
        selectedRepoAgentId,
        "system",
        "Could not send the message because the session is disconnected.",
      );
    }
  };

  const handleKeyPress = (event: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      handleSendMessage();
    }
  };

  const visibleMessages =
    selectedMessages.length > 0
      ? selectedMessages
      : [
          {
            id: "welcome-message",
            role: "assistant" as const,
            content:
              "Hello! I'm JARVIS. Ask me to explain the code or make a change and I'll guide the flow from here.",
            timestamp: new Date(),
          },
        ];

  return (
    <div className="main-page">
      <aside className="sidebar">
        <div className="sidebar-header">
          <h2 className="sidebar-title">Workspaces</h2>
        </div>

        <div className="folders-list">
          {folders.map((folder) => {
            const pendingCount = pendingTurns.filter(
              (turn) => turn.repoAgentId === folder.repoAgentId && turn.requiresUserResponse,
            ).length;

            return (
              <button
                key={folder.id}
                className={`folder-item ${selectedFolderId === folder.id ? "active" : ""}`}
                onClick={() => setSelectedFolderId(folder.id)}
              >
                <svg
                  className="folder-icon-small"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                >
                  <path d="M3 7v10a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V9a2 2 0 0 0-2-2h-6l-2-2H5a2 2 0 0 0-2 2z" />
                </svg>
                <span className="folder-name">{folder.name}</span>
                {pendingCount > 0 ? (
                  <span className="folder-pending-count">{pendingCount}</span>
                ) : null}
              </button>
            );
          })}
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

      <div className="chat-container">
        <div className="chat-header">
          <div className="chat-header-info">
            <h3 className="chat-title">{selectedFolder?.name}</h3>
            <p className="chat-subtitle">{selectedFolder?.path}</p>
            {selectedRepoAgentId && selectedRepoAgentId !== activeRepoAgentId ? (
              <p className="chat-note">
                The next message will switch the active session to this workspace.
              </p>
            ) : null}
          </div>
          <div className={`connection-status ${isConnected ? "connected" : "disconnected"}`}>
            <span className="status-dot"></span>
            {isConnected ? "Connected" : "Disconnected"}
          </div>
        </div>

        {selectedPendingTurn ? (
          <div className="pending-turn-banner">
            <strong>{selectedPendingTurn.type}</strong>
            <span>{selectedPendingTurn.message}</span>
          </div>
        ) : null}

        <div className="messages-container">
          {visibleMessages.map((message) => (
            <div
              key={message.id}
              className={`message ${
                message.role === "user" ? "user-message" : "assistant-message"
              }`}
            >
              <div className="message-avatar">
                {message.role === "user" ? (
                  <svg viewBox="0 0 24 24" fill="currentColor" width="20" height="20">
                    <path d="M12 12c2.21 0 4-1.79 4-4s-1.79-4-4-4-4 1.79-4 4 1.79 4 4 4zm0 2c-2.67 0-8 1.34-8 4v2h16v-2c0-2.66-5.33-4-8-4z" />
                  </svg>
                ) : (
                  <span className="assistant-avatar">{message.role === "system" ? "S" : "J"}</span>
                )}
              </div>
              <div className="message-content">
                <div className="message-text">
                  {message.content}
                </div>
              </div>
            </div>
          ))}

          {isLoading ? (
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
                <div className="message-text">{loadingStatus}</div>
              </div>
            </div>
          ) : null}
          <div ref={messagesEndRef} />
        </div>

        <div className="input-container">
          <textarea
            ref={inputRef}
            className="message-input"
            placeholder="Ask JARVIS anything about your code..."
            value={inputMessage}
            onChange={(event) => setInputMessage(event.target.value)}
            onKeyDown={handleKeyPress}
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

function handleServerMessage(
  message: ServerToClientMessage,
  setSessionId: Dispatch<SetStateAction<string | null>>,
  setActiveRepoAgentId: Dispatch<SetStateAction<string | null>>,
  setPendingTurns: Dispatch<SetStateAction<PendingTurnSummary[]>>,
  setFolders: Dispatch<SetStateAction<Folder[]>>,
  setMessagesByRepo: Dispatch<SetStateAction<Record<string, Message[]>>>,
  setIsLoading: Dispatch<SetStateAction<boolean>>,
): void {
  if (message.type === "SESSION_STATE") {
    const state = message as SessionStateMessage;
    setSessionId(state.sessionId);
    setActiveRepoAgentId(state.activeRepoAgentId ?? null);
    setPendingTurns(state.pendingTurns);
    setFolders((prev) => mergeSessionFolders(prev, state.repos));
    if (state.activeRepoAgentId) {
      setMessagesByRepo((prev) => ({
        ...prev,
        [state.activeRepoAgentId!]: state.messages.map(mapVoiceMessage),
      }));
    }
    if (state.messages.length > 0) {
      setIsLoading(false);
    }
    return;
  }

  if (message.type === "CHAT_MESSAGE") {
    const chatMessage = mapVoiceMessage(message as VoiceChatMessage);
    const repoAgentId = (message as VoiceChatMessage).repoAgentId;
    setMessagesByRepo((prev) => ({
      ...prev,
      [repoAgentId]: upsertMessage(prev[repoAgentId] || [], chatMessage),
    }));
    if (chatMessage.role !== "user") {
      setIsLoading(false);
    }
    return;
  }

  if (message.type === "PENDING_TURN") {
    const pending = (message as PendingTurnMessage).pendingTurn;
    setPendingTurns((prev) => upsertPendingTurn(prev, pending));
    setIsLoading(false);
    return;
  }

  if (message.type === "AI_RESPONSE" || message.type === "AUDIO_STREAM_START") {
    setIsLoading(false);
  }
}

function appendLocalMessage(
  setMessagesByRepo: Dispatch<SetStateAction<Record<string, Message[]>>>,
  repoAgentId: string | undefined,
  role: Message["role"],
  content: string,
): void {
  const key = repoAgentId || "local";
  const message: Message = {
    id: `local-${Date.now()}-${Math.random().toString(16).slice(2)}`,
    role,
    content,
    timestamp: new Date(),
  };
  setMessagesByRepo((prev) => ({
    ...prev,
    [key]: [...(prev[key] || []), message],
  }));
}

function mergeSessionFolders(existing: Folder[], repos: RepoSummary[]): Folder[] {
  return repos.reduce((folders, repo) => {
    const nextFolder: Folder = {
      id: `folder-${repo.repoAgentId}`,
      name: repo.displayName,
      path: repo.repoPath,
      repoAgentId: repo.repoAgentId,
    };
    return upsertFolder(folders, nextFolder);
  }, existing);
}

function upsertFolder(folders: Folder[], next: Folder): Folder[] {
  const existingIndex = folders.findIndex(
    (folder) =>
      folder.repoAgentId === next.repoAgentId || folder.path === next.path || folder.id === next.id,
  );
  if (existingIndex === -1) {
    return [...folders, next];
  }

  return folders.map((folder, index) =>
    index === existingIndex ? { ...folder, ...next, id: folder.id } : folder,
  );
}

function mapVoiceMessage(message: VoiceChatMessage): Message {
  return {
    id: message.id,
    role: message.role,
    content: message.content,
    timestamp: new Date(message.createdAt),
    turnId: message.turnId,
  };
}

function upsertMessage(messages: Message[], next: Message): Message[] {
  const existingIndex = messages.findIndex((message) => message.id === next.id);
  if (existingIndex === -1) {
    return [...messages, next];
  }

  return messages.map((message, index) => (index === existingIndex ? next : message));
}

function upsertPendingTurn(
  pendingTurns: PendingTurnSummary[],
  next: PendingTurnSummary,
): PendingTurnSummary[] {
  const existingIndex = pendingTurns.findIndex((turn) => turn.turnId === next.turnId);
  if (existingIndex === -1) {
    return [...pendingTurns, next];
  }

  return pendingTurns.map((turn, index) => (index === existingIndex ? next : turn));
}

function isApproval(text: string): boolean {
  const normalized = text.trim().toLowerCase();
  return ["yes", "y", "ok", "okay", "dale", "si", "sí", "vale"].includes(normalized);
}

export default MainPage;
