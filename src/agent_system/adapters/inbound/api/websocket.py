"""WebSocket connection manager for real-time group chat."""

import asyncio
import json
import logging
from datetime import datetime
from enum import Enum
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect
from pydantic import BaseModel

logger = logging.getLogger(__name__)


class WebSocketMessageType(str, Enum):
    """Types of WebSocket messages."""

    # Client -> Server
    MESSAGE = "message"
    TYPING = "typing"
    STOP_TYPING = "stop_typing"
    
    # Server -> Client
    USER_JOINED = "user_joined"
    USER_LEFT = "user_left"
    NEW_MESSAGE = "new_message"
    TYPING_UPDATE = "typing_update"
    EVENT_EXTRACTED = "event_extracted"
    AGENT_THINKING = "agent_thinking"
    AGENT_RESPONSE = "agent_response"
    AGENT_CHUNK = "agent_chunk"        # Streaming text chunk
    AGENT_COMPLETE = "agent_complete"  # Stream complete
    ERROR = "error"


class WebSocketMessage(BaseModel):
    """WebSocket message structure."""

    type: WebSocketMessageType
    data: dict[str, Any]
    timestamp: datetime = None
    sender_id: str | None = None

    def __init__(self, **data):
        if "timestamp" not in data or data["timestamp"] is None:
            data["timestamp"] = datetime.utcnow()
        super().__init__(**data)

    def to_json(self) -> str:
        """Convert to JSON string."""
        return json.dumps({
            "type": self.type.value,
            "data": self.data,
            "timestamp": self.timestamp.isoformat(),
            "sender_id": self.sender_id,
        })

    @classmethod
    def from_json(cls, json_str: str) -> "WebSocketMessage":
        """Parse from JSON string."""
        data = json.loads(json_str)
        return cls(
            type=WebSocketMessageType(data["type"]),
            data=data.get("data", {}),
            timestamp=datetime.fromisoformat(data["timestamp"]) if data.get("timestamp") else None,
            sender_id=data.get("sender_id"),
        )


class ConnectionManager:
    """Manage WebSocket connections for group chats."""

    def __init__(self):
        # group_id -> conversation_id -> {user_id -> WebSocket}
        self.active_connections: dict[str, dict[str, dict[str, WebSocket]]] = {}
        # Track typing users: group_id -> conversation_id -> set of user_ids
        self.typing_users: dict[str, dict[str, set[str]]] = {}
        # User info cache: user_id -> email/name
        self.user_info: dict[str, str] = {}
        # Lock for thread-safe operations
        self._lock = asyncio.Lock()

    async def connect(
        self,
        websocket: WebSocket,
        group_id: str,
        conversation_id: str,
        user_id: str,
        user_info: str | None = None,
    ) -> None:
        """Accept and register a WebSocket connection."""
        await websocket.accept()
        
        async with self._lock:
            # Initialize nested dicts if needed
            if group_id not in self.active_connections:
                self.active_connections[group_id] = {}
                self.typing_users[group_id] = {}
            
            if conversation_id not in self.active_connections[group_id]:
                self.active_connections[group_id][conversation_id] = {}
                self.typing_users[group_id][conversation_id] = set()
            
            # Store connection
            self.active_connections[group_id][conversation_id][user_id] = websocket
            
            # Cache user info
            if user_info:
                self.user_info[user_id] = user_info
        
        # Broadcast user joined
        await self.broadcast_to_conversation(
            group_id,
            conversation_id,
            WebSocketMessage(
                type=WebSocketMessageType.USER_JOINED,
                data={
                    "user_id": user_id,
                    "user_info": user_info or user_id,
                    "online_users": await self.get_online_users(group_id, conversation_id),
                },
            ),
            exclude_user=user_id,
        )
        
        logger.info(f"User {user_id} connected to group {group_id}, conversation {conversation_id}")

    async def disconnect(
        self,
        group_id: str,
        conversation_id: str,
        user_id: str,
    ) -> None:
        """Remove a WebSocket connection."""
        async with self._lock:
            if (
                group_id in self.active_connections
                and conversation_id in self.active_connections[group_id]
                and user_id in self.active_connections[group_id][conversation_id]
            ):
                del self.active_connections[group_id][conversation_id][user_id]
                
                # Remove from typing users
                if (
                    group_id in self.typing_users
                    and conversation_id in self.typing_users[group_id]
                ):
                    self.typing_users[group_id][conversation_id].discard(user_id)
                
                # Clean up empty dicts
                if not self.active_connections[group_id][conversation_id]:
                    del self.active_connections[group_id][conversation_id]
                    if conversation_id in self.typing_users.get(group_id, {}):
                        del self.typing_users[group_id][conversation_id]
                
                if not self.active_connections[group_id]:
                    del self.active_connections[group_id]
                    if group_id in self.typing_users:
                        del self.typing_users[group_id]
        
        # Broadcast user left
        await self.broadcast_to_conversation(
            group_id,
            conversation_id,
            WebSocketMessage(
                type=WebSocketMessageType.USER_LEFT,
                data={
                    "user_id": user_id,
                    "online_users": await self.get_online_users(group_id, conversation_id),
                },
            ),
        )
        
        logger.info(f"User {user_id} disconnected from group {group_id}, conversation {conversation_id}")

    async def get_online_users(self, group_id: str, conversation_id: str) -> list[str]:
        """Get list of online users in a conversation."""
        async with self._lock:
            if (
                group_id in self.active_connections
                and conversation_id in self.active_connections[group_id]
            ):
                return list(self.active_connections[group_id][conversation_id].keys())
            return []

    async def broadcast_to_conversation(
        self,
        group_id: str,
        conversation_id: str,
        message: WebSocketMessage,
        exclude_user: str | None = None,
    ) -> None:
        """Send a message to all users in a conversation."""
        connections = {}
        
        async with self._lock:
            if (
                group_id in self.active_connections
                and conversation_id in self.active_connections[group_id]
            ):
                connections = dict(self.active_connections[group_id][conversation_id])
        
        json_message = message.to_json()
        
        for user_id, websocket in connections.items():
            if user_id != exclude_user:
                try:
                    await websocket.send_text(json_message)
                except Exception as e:
                    logger.warning(f"Failed to send to user {user_id}: {e}")

    async def broadcast_to_group(
        self,
        group_id: str,
        message: WebSocketMessage,
        exclude_user: str | None = None,
    ) -> None:
        """Send a message to all users in all conversations of a group."""
        conversations = {}
        
        async with self._lock:
            if group_id in self.active_connections:
                conversations = dict(self.active_connections[group_id])
        
        for conversation_id in conversations:
            await self.broadcast_to_conversation(
                group_id,
                conversation_id,
                message,
                exclude_user,
            )

    async def send_to_user(
        self,
        group_id: str,
        conversation_id: str,
        user_id: str,
        message: WebSocketMessage,
    ) -> bool:
        """Send a message to a specific user."""
        websocket = None
        
        async with self._lock:
            if (
                group_id in self.active_connections
                and conversation_id in self.active_connections[group_id]
                and user_id in self.active_connections[group_id][conversation_id]
            ):
                websocket = self.active_connections[group_id][conversation_id][user_id]
        
        if websocket:
            try:
                await websocket.send_text(message.to_json())
                return True
            except Exception as e:
                logger.warning(f"Failed to send to user {user_id}: {e}")
        
        return False

    async def set_typing(
        self,
        group_id: str,
        conversation_id: str,
        user_id: str,
        is_typing: bool,
    ) -> None:
        """Update typing status and broadcast to others."""
        async with self._lock:
            if (
                group_id not in self.typing_users
                or conversation_id not in self.typing_users[group_id]
            ):
                return
            
            if is_typing:
                self.typing_users[group_id][conversation_id].add(user_id)
            else:
                self.typing_users[group_id][conversation_id].discard(user_id)
            
            typing_list = list(self.typing_users[group_id][conversation_id])
        
        # Broadcast typing update
        await self.broadcast_to_conversation(
            group_id,
            conversation_id,
            WebSocketMessage(
                type=WebSocketMessageType.TYPING_UPDATE,
                data={
                    "typing_users": typing_list,
                },
            ),
            exclude_user=user_id,
        )

    async def broadcast_new_message(
        self,
        group_id: str,
        conversation_id: str,
        message_id: str,
        sender_id: str,
        content: str,
        role: str,
        tool_calls: list[dict] | None = None,
    ) -> None:
        """Broadcast a new message to the conversation."""
        await self.broadcast_to_conversation(
            group_id,
            conversation_id,
            WebSocketMessage(
                type=WebSocketMessageType.NEW_MESSAGE,
                data={
                    "message_id": message_id,
                    "sender_id": sender_id,
                    "content": content,
                    "role": role,
                    "tool_calls": tool_calls or [],
                },
                sender_id=sender_id,
            ),
        )
        
        # Clear typing status for sender
        await self.set_typing(group_id, conversation_id, sender_id, False)

    async def broadcast_event_extracted(
        self,
        group_id: str,
        conversation_id: str,
        event_data: dict,
    ) -> None:
        """Broadcast when a new event is extracted from conversation."""
        await self.broadcast_to_conversation(
            group_id,
            conversation_id,
            WebSocketMessage(
                type=WebSocketMessageType.EVENT_EXTRACTED,
                data=event_data,
            ),
        )

    async def broadcast_agent_status(
        self,
        group_id: str,
        conversation_id: str,
        status: str,
        node_name: str | None = None,
        data: dict | None = None,
    ) -> None:
        """Broadcast agent thinking/processing status."""
        await self.broadcast_to_conversation(
            group_id,
            conversation_id,
            WebSocketMessage(
                type=WebSocketMessageType.AGENT_THINKING,
                data={
                    "status": status,
                    "node_name": node_name,
                    "details": data or {},
                },
            ),
        )

    async def broadcast_agent_chunk(
        self,
        group_id: str,
        conversation_id: str,
        message_id: str,
        chunk: str,
        is_complete: bool = False,
    ) -> None:
        """Broadcast a streaming agent response chunk."""
        message_type = WebSocketMessageType.AGENT_COMPLETE if is_complete else WebSocketMessageType.AGENT_CHUNK
        await self.broadcast_to_conversation(
            group_id,
            conversation_id,
            WebSocketMessage(
                type=message_type,
                data={
                    "message_id": message_id,
                    "chunk": chunk,
                    "is_complete": is_complete,
                },
            ),
        )


# Global connection manager instance
connection_manager = ConnectionManager()
