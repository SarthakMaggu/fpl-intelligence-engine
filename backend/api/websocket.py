"""
WebSocket Manager — mirrors war-intel-dashboard socket.manager pattern.

FastAPI WebSocket + Redis pub/sub for live score broadcasting.
Multiple browser tabs connect → all receive live score updates from
the single background polling task via Redis pub/sub fan-out.
"""
import asyncio
import uuid
import orjson
from fastapi import WebSocket, WebSocketDisconnect
from loguru import logger


class WebSocketManager:
    def __init__(self):
        self._connections: dict[str, WebSocket] = {}
        self._pubsub_task: asyncio.Task | None = None

    async def connect(self, ws: WebSocket) -> str:
        """Accept a new WebSocket connection. Returns client_id."""
        await ws.accept()
        client_id = str(uuid.uuid4())[:8]
        self._connections[client_id] = ws
        logger.debug(f"WebSocket connected: {client_id} (total: {len(self._connections)})")
        return client_id

    def disconnect(self, client_id: str) -> None:
        self._connections.pop(client_id, None)
        logger.debug(f"WebSocket disconnected: {client_id} (remaining: {len(self._connections)})")

    async def send_to(self, client_id: str, event: str, data: dict) -> None:
        """Send a message to a specific client."""
        ws = self._connections.get(client_id)
        if ws:
            try:
                await ws.send_text(
                    orjson.dumps({"event": event, "data": data}).decode()
                )
            except Exception:
                self.disconnect(client_id)

    async def broadcast(self, event: str, data: dict) -> None:
        """Broadcast a message to all connected clients. Remove dead connections."""
        if not self._connections:
            return

        message = orjson.dumps({"event": event, "data": data}).decode()
        dead_clients = []

        for client_id, ws in self._connections.items():
            try:
                await ws.send_text(message)
            except Exception:
                dead_clients.append(client_id)

        for cid in dead_clients:
            self.disconnect(cid)

    async def start_pubsub_listener(self) -> None:
        """
        Subscribe to Redis pub/sub channels and broadcast to all WebSocket clients.
        Runs as a background task during app lifetime.
        """
        from core.redis_client import redis_client
        logger.info("Starting Redis pub/sub listener for live scores")

        while True:
            try:
                async with redis_client.pubsub() as pubsub:
                    await pubsub.subscribe("fpl:live:scores", "fpl:pipeline:status")
                    async for message in pubsub.listen():
                        if message["type"] != "message":
                            continue
                        try:
                            channel = message["channel"]
                            raw_data = orjson.loads(message["data"])

                            if channel == "fpl:live:scores":
                                await self.broadcast("live:score_update", raw_data)
                            elif channel == "fpl:pipeline:status":
                                await self.broadcast("pipeline:status", raw_data)

                        except Exception as e:
                            logger.warning(f"pubsub message parse error: {e}")

            except asyncio.CancelledError:
                logger.info("WebSocket pub/sub listener cancelled")
                break
            except Exception as e:
                logger.error(f"pub/sub listener error: {e}. Reconnecting in 5s...")
                await asyncio.sleep(5)

    def connection_count(self) -> int:
        return len(self._connections)


# Singleton instance
ws_manager = WebSocketManager()

# ── Router ─────────────────────────────────────────────────────────────────────
from fastapi import APIRouter

router = APIRouter()


@router.websocket("/ws/live")
async def websocket_live(websocket: WebSocket):
    """Accept WebSocket connections for live scoring fan-out."""
    client_id = await ws_manager.connect(websocket)
    try:
        while True:
            # Keep connection alive; we only push data server → client
            await websocket.receive_text()
    except WebSocketDisconnect:
        ws_manager.disconnect(client_id)


async def start_pubsub_listener(_manager=None) -> None:
    """
    Module-level wrapper so main.py can call:
        asyncio.create_task(start_pubsub_listener(ws_manager))
    The `_manager` arg is accepted but ignored — ws_manager singleton is used.
    """
    await ws_manager.start_pubsub_listener()
