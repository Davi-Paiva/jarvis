from __future__ import annotations

import json
from typing import Any
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
        logger.info(f"Sent connection confirmation to client {client_id}")
        
        while True:
            # Receive message from client
            logger.info(f"Waiting for message from client {client_id}...")
            data = await websocket.receive_text()
            logger.info(f"Received raw data from client {client_id}: {data}")
            message_data = json.loads(data)
            
            logger.info(f"Parsed message from client {client_id}: {message_data}")
            
            if message_data.get("type") == "message":
                logger.info(f"Processing message from client {client_id}: {message_data.get('content')}")
                # Send start signal
                await manager.send_message({
                    "type": "start",
                    "message_id": f"msg_{client_id}"
                }, client_id)
                logger.info(f"Sent start signal to client {client_id}")
                
                # TODO: Integrate with your orchestrator/LLM service
                # For now, echo back with processing indication
                user_message = message_data.get("content", "")
                
                # Simulate streaming response (replace with actual LLM streaming)
                response_text = f"Processing: {user_message}"
                logger.info(f"Streaming response to client {client_id}: {response_text}")
                
                # Stream tokens (simulate)
                for i, char in enumerate(response_text):
                    await manager.send_message({
                        "type": "token",
                        "content": char,
                        "index": i
                    }, client_id)
                
                logger.info(f"Finished streaming to client {client_id}")
                # Send end signal
                await manager.send_message({
                    "type": "end",
                    "message_id": f"msg_{client_id}",
                    "content": response_text
                }, client_id)
                logger.info(f"Sent end signal to client {client_id}")
            
            elif message_data.get("type") == "ping":
                logger.info(f"Received ping from client {client_id}, sending pong")
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
