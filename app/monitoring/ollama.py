"""
Ollama server monitoring for Ollama Monitor.

Periodically polls the Ollama server (/api/version, /api/tags, /api/ps),
updates the local model list and broadcasts status over WebSocket.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

import httpx
from sqlalchemy import select

from app.config import Config
from app.database import Model, get_session
from app.services.websocket_manager import websocket_manager

logger = logging.getLogger(__name__)


class OllamaMonitor:
    def __init__(self, config: Config, websocket_manager) -> None:
        self.config = config
        self.websocket_manager = websocket_manager
        self.http_client = httpx.AsyncClient(
            timeout=httpx.Timeout(self.config.ollama_timeout, connect=5.0)
        )
        self.running = False
        self.last_status: Dict[str, Any] = {"status": "unknown", "message": "not checked yet"}

    async def check_ollama_status(self) -> Dict[str, Any]:
        """Check server reachability and version; broadcast the result."""
        try:
            response = await self.http_client.get(f"{self.config.ollama_base_url}/api/version")
            if response.status_code == 200:
                data = response.json()
                status = {
                    "status": "healthy",
                    "message": "Ollama server is running",
                    "version": data.get("version", "unknown"),
                }
                self.last_status = status
                await self.websocket_manager.send_event("ollama_status_updated", status)
                return status
            status = {
                "status": "error",
                "message": f"Ollama server not responding: {response.status_code}",
            }
            self.last_status = status
            await self.websocket_manager.send_event("ollama_status_updated", status)
            return status
        except httpx.RequestError as e:
            status = {"status": "error", "message": f"Ollama server not reachable: {e}"}
            self.last_status = status
            await self.websocket_manager.send_event("ollama_status_updated", status)
            return status
        except Exception as e:  # pragma: no cover
            status = {"status": "error", "message": f"Error checking Ollama: {e}"}
            self.last_status = status
            await self.websocket_manager.send_event("ollama_status_updated", status)
            return status

    async def get_model_info(self) -> None:
        """Fetch /api/tags and sync the local model table."""
        try:
            response = await self.http_client.get(f"{self.config.ollama_base_url}/api/tags")
            if response.status_code != 200:
                logger.warning("Failed to get model list: %s", response.status_code)
                return
            data = response.json()
            models = data.get("models", [])
        except httpx.RequestError as e:
            logger.warning("Error fetching model list: %s", e)
            return

        try:
            async with await get_session() as session:
                result = await session.execute(select(Model))
                existing = {m.name: m for m in result.scalars().all()}
                now = datetime.utcnow()
                for md in models:
                    name = md.get("name")
                    if not name:
                        continue
                    details = md.get("details") or {}
                    model = existing.get(name)
                    if model is None:
                        model = Model(name=name)
                        session.add(model)
                        existing[name] = model
                    model.size = md.get("size")
                    model.quantization_type = details.get("quantization_level")
                    model.context_length = md.get("context_length")
                    if not model.last_loaded:
                        model.last_loaded = now
                await session.commit()
        except Exception as e:
            logger.error("Error syncing model list: %s", e)

        await self.websocket_manager.send_event("models_updated", {"count": len(models)})

    async def get_loaded_models(self) -> List[Dict[str, Any]]:
        """Fetch /api/ps - models currently loaded into memory."""
        try:
            response = await self.http_client.get(f"{self.config.ollama_base_url}/api/ps")
            if response.status_code != 200:
                return []
            data = response.json()
            return data.get("models", [])
        except httpx.RequestError as e:
            logger.warning("Error fetching /api/ps: %s", e)
            return []

    async def run(self) -> None:
        """Monitoring loop: poll status and models periodically."""
        while self.running:
            try:
                await self.check_ollama_status()
                await self.get_model_info()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Error in Ollama monitoring loop: %s", e)
            await asyncio.sleep(self.config.monitoring_ollama_interval)


async def start_monitoring() -> OllamaMonitor:
    """Create the monitor singleton without blocking (loop runs as a task)."""
    global ollama_monitor
    config = Config()
    from app.services.websocket_manager import websocket_manager as _ws
    ollama_monitor = OllamaMonitor(config, _ws)
    ollama_monitor.running = True
    return ollama_monitor


async def run() -> None:
    """Run the monitoring loop (invoked as a background task)."""
    global ollama_monitor
    if ollama_monitor is None:
        await start_monitoring()
    if ollama_monitor:
        await ollama_monitor.run()


async def stop_monitoring() -> None:
    global ollama_monitor
    if ollama_monitor:
        ollama_monitor.running = False


ollama_monitor: Optional[OllamaMonitor] = None
