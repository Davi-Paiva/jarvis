from __future__ import annotations

import json
from typing import Any, Optional
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status

from app.models.schemas import ChatMessage, ChatMessageRole

logger = logging.getLogger(__name__)
router = APIRouter()


class ConnectionManager:
    """Manages WebSocket connections for chat sessions."""
    
    def __init__(self):
        self.active_connections: dict[str, WebSocket] = {}
    
    async def connect(self, websocket: WebSocket, client_id: str):
        await websocket.accept()
        self.active_connections[client_id] = websocket
    
    def disconnect(self, client_id: str):
        if client_id in self.active_connections:
            del self.active_connections[client_id]
    
    async def send_message(self, message: dict[str, Any], client_id: str):
        if client_id in self.active_connections:
            await self.active_connections[client_id].send_json(message)
    
    async def send_text(self, text: str, client_id: str):
        if client_id in self.active_connections:
            await self.active_connections[client_id].send_text(text)


manager = ConnectionManager()


@router.websocket("/ws/chat/{repo_id}/{client_id}")
async def chat_websocket(
    websocket: WebSocket,
    repo_id: str,
    client_id: str,
):
    """
    WebSocket endpoint for real-time chat with the AI assistant.
    
    Messages from client should be JSON:
    {
        "type": "message",
        "content": "user message here",
        "thread_id": "optional-thread-id"
    }
    
    Server responses:
    {
        "type": "token" | "message" | "error" | "start" | "end",
        "content": "...",
        "message_id": "..."
    }
    """
    await manager.connect(websocket, client_id)
    logger.info(f"WebSocket connected: repo_id={repo_id}, client_id={client_id}")
    
    try:
        # Send connection confirmation
        await manager.send_message({
            "type": "connected",
            "repo_id": repo_id,
            "message": "Connected to chat"
        }, client_id)
        
        while True:
            data = await websocket.receive_text()
            
            try:
                message_data = json.loads(data)
            except json.JSONDecodeError as e:
                logger.error(f"Failed to parse JSON from client {client_id}: {e}")
                await manager.send_message({
                    "type": "error",
                    "content": "Invalid JSON format"
                }, client_id)
                continue
            
            if message_data.get("type") == "message":
                user_message = message_data.get("content", "")
                
                # Send start signal
                await manager.send_message({
                    "type": "start",
                    "message_id": f"msg_{client_id}"
                }, client_id)
                orchestrator = websocket.app.state.orchestrator

                resolved_repo_agent_id = _resolve_repo_agent_id(orchestrator, repo_id)
                if resolved_repo_agent_id is None:
                    raise RuntimeError(f"Could not resolve repo agent for identifier: {repo_id}")

                pending_turn = await _get_latest_pending_turn_for_repo(orchestrator, resolved_repo_agent_id)
                if pending_turn is not None:
                    result = await orchestrator.submit_user_response(
                        turn_id=pending_turn.id,
                        response=user_message,
                        approved=None,
                    )
                else:
                    result = await orchestrator.handle_user_message(
                        repo_agent_id=resolved_repo_agent_id,
                        message=user_message,
                    )

                latest_pending_turn = await _get_latest_pending_turn_for_repo(
                    orchestrator,
                    resolved_repo_agent_id,
                )
                response_text = _extract_response_text(result, latest_pending_turn)
                
                # Stream tokens to preserve current desktop chat protocol
                for i, char in enumerate(response_text):
                    await manager.send_message({
                        "type": "token",
                        "content": char,
                        "index": i
                    }, client_id)
                
                # Build end message with turn information if available
                end_message = {
                    "type": "end",
                    "message_id": f"msg_{client_id}",
                    "content": response_text
                }
                
                if latest_pending_turn is not None:
                    end_message["turn_id"] = latest_pending_turn.id
                    end_message["turn_type"] = latest_pending_turn.type.value
                    end_message["requires_response"] = latest_pending_turn.requires_user_response
                
                # Send end signal
                await manager.send_message(end_message, client_id)
            
            elif message_data.get("type") == "ping":
                await manager.send_message({
                    "type": "pong"
                }, client_id)
            else:
                logger.warning(f"Unknown message type from client {client_id}: {message_data.get('type')}")
    
    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected: client_id={client_id}")
        manager.disconnect(client_id)
    except Exception as e:
        logger.error(f"Error in WebSocket for client {client_id}: {e}", exc_info=True)
        # Send error to client before closing
        try:
            await manager.send_message({
                "type": "error",
                "content": str(e)
            }, client_id)
        except:
            pass
        manager.disconnect(client_id)


def _resolve_repo_agent_id(orchestrator: Any, repo_identifier: str) -> Optional[str]:
    # Accept both repo_agent_id and repo_id for compatibility with current desktop payload.
    if repo_identifier.startswith("repo_agent_"):
        try:
            orchestrator.registry.get_agent_state(repo_identifier)
            return repo_identifier
        except Exception:
            return None

    for state in orchestrator.registry.list_agents(user_id=orchestrator.settings.jarvis_user_id):
        if state.repo_id == repo_identifier:
            return state.repo_agent_id
    return None


def _extract_response_text(result: Any, latest_pending_turn: Optional[Any] = None) -> str:
    """Extract response text from result, ensuring full message is returned."""
    extracted_text = ""
    
    if latest_pending_turn is not None and getattr(latest_pending_turn, "message", None):
        extracted_text = str(latest_pending_turn.message)
        return extracted_text

    next_turn = getattr(result, "next_turn", None)
    if next_turn is not None and getattr(next_turn, "message", None):
        extracted_text = str(next_turn.message)
        return extracted_text

    agent = getattr(result, "agent", None)
    if agent is not None:
        if getattr(agent, "last_explanation", None):
            extracted_text = str(agent.last_explanation)
            return extracted_text
        if getattr(agent, "final_report", None):
            extracted_text = str(agent.final_report)
            return extracted_text

    return "I understood your request and started processing it."


async def _get_latest_pending_turn_for_repo(orchestrator: Any, repo_agent_id: str) -> Optional[Any]:
    pending_turns = await orchestrator.list_pending_turns(user_id=orchestrator.settings.jarvis_user_id)
    repo_turns = [
        turn
        for turn in pending_turns
        if turn.repo_agent_id == repo_agent_id and turn.requires_user_response
    ]
    if not repo_turns:
        return None
    return max(repo_turns, key=lambda item: item.created_at)
