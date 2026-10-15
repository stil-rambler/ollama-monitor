"""
WebSocket event manager for Ollama Monitor.

Broadcasts JSON events to connected browser clients over /ws/monitor.
Clients that are slow or stale are dropped without blocking the event loop
or the proxy pipeline.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Dict, Optional, Set

from fastapi import WebSocket

logger = logging.getLogger(__name__)

# Module-level singleton shared by monitors, proxy and main app.
websocket_manager: "WebSocketManager" = None  # type: ignore[assignment]

MAX_QUEUE_SIZE = 200  # drop a client when its outbound queue exceeds this
PING_INTERVAL = 20.0
MAX_CLIENT_AGE = 7200  # seconds; reconnect handshake refreshes the age


class WebSocketManager:
    """Manages WebSocket connections and event broadcast."""

    def __init__(self) -> None:
        self._connections: Dict[WebSocket, "ClientHandle"] = {}
        self._lock = asyncio.Lock()
        self._monitor_task: Optional[asyncio.Task] = None
        self._stats = {
            "total_connections": 0,
            "current_connections": 0,
            "total_events": 0,
            "dropped_slow": 0,
        }

    async def connect(self, websocket: WebSocket) -> None:
        """Accept a new client and start its writer task."""
        await websocket.accept()
        handle = ClientHandle(websocket, self._stats)
        await handle.start()
        async with self._lock:
            self._connections[websocket] = handle
            self._stats["total_connections"] += 1
            self._stats["current_connections"] = len(self._connections)
        logger.info("WebSocket client connected (%d active)", len(self._connections))
        await self._ensure_monitor_task()

    async def disconnect(self, websocket: WebSocket) -> None:
        """Remove a client and cancel its writer task."""
        async with self._lock:
            handle = self._connections.pop(websocket, None)
            if handle:
                self._stats["current_connections"] = len(self._connections)
        if handle:
            await handle.close()
            logger.info("WebSocket client disconnected (%d active)", len(self._connections))

    async def send_event(self, event_type: str, data: Any = None) -> None:
        """Broadcast an event to all connected clients (non-blocking)."""
        payload = json.dumps(
            {"type": event_type, "data": data, "ts": time.time()}, ensure_ascii=False, default=str
        )
        self._stats["total_events"] += 1
        to_remove: list[WebSocket] = []
        async with self._lock:
            handles = list(self._connections.values())
        for handle in handles:
            await handle.enqueue(payload, to_remove)
        if to_remove:
            async with self._lock:
                for ws in to_remove:
                    h = self._connections.pop(ws, None)
                    if h:
                        await h.close()
                self._stats["current_connections"] = len(self._connections)
            logger.info("Dropped %d slow WebSocket client(s)", len(to_remove))

    async def _ensure_monitor_task(self) -> None:
        if self._monitor_task is None or self._monitor_task.done():
            self._monitor_task = asyncio.create_task(self._monitor_loop())

    async def _monitor_loop(self) -> None:
        """Periodically ping clients and remove dead/stale ones."""
        try:
            while True:
                await asyncio.sleep(PING_INTERVAL)
                to_remove: list[WebSocket] = []
                async with self._lock:
                    handles = list(self._connections.values())
                for handle in handles:
                    if handle.is_stale():
                        to_remove.append(handle.ws)
                    elif not await handle.ping():
                        to_remove.append(handle.ws)
                if to_remove:
                    async with self._lock:
                        for ws in to_remove:
                            h = self._connections.pop(ws, None)
                            if h:
                                await h.close()
                        self._stats["current_connections"] = len(self._connections)
        except asyncio.CancelledError:
            pass
        except Exception:  # pragma: no cover
            logger.exception("WebSocket monitor loop error")

    async def shutdown(self) -> None:
        """Close all connections and stop the monitor task."""
        if self._monitor_task:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except (asyncio.CancelledError, Exception):
                pass
        async with self._lock:
            handles = list(self._connections.values())
            self._connections.clear()
        for h in handles:
            await h.close()

    def get_stats(self) -> dict:
        return dict(self._stats)


class ClientHandle:
    """Outbound event queue for a single WebSocket client."""

    def __init__(self, ws: WebSocket, stats: dict) -> None:
        self.ws = ws
        self.stats = stats
        self.queue: asyncio.Queue[str] = asyncio.Queue(maxsize=MAX_QUEUE_SIZE)
        self.last_seen = time.time()
        self.writer_task: Optional[asyncio.Task] = None

    async def enqueue(self, payload: str, to_remove: list) -> None:
        """Put an event on the queue or mark the client for removal."""
        try:
            self.queue.put_nowait(payload)
        except asyncio.QueueFull:
            self.stats["dropped_slow"] += 1
            to_remove.append(self.ws)

    def is_stale(self) -> bool:
        return time.time() - self.last_seen > MAX_CLIENT_AGE

    async def ping(self) -> bool:
        try:
            self.last_seen = time.time()
            await self.ws.send_text("__ping__")
            return True
        except Exception:
            return False

    async def _writer_loop(self) -> None:
        try:
            while True:
                payload = await self.queue.get()
                await self.ws.send_text(payload)
        except asyncio.CancelledError:
            pass
        except Exception:
            pass

    async def start(self) -> None:
        if self.writer_task is None or self.writer_task.done():
            self.writer_task = asyncio.create_task(self._writer_loop())

    async def close(self) -> None:
        if self.writer_task:
            self.writer_task.cancel()
            try:
                await self.writer_task
            except (asyncio.CancelledError, Exception):
                pass
        try:
            await self.ws.close()
        except Exception:
            pass
