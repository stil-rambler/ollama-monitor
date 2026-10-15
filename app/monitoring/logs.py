"""
Application + Ollama log management for Ollama Monitor.

Reads the local log file and (if present) Ollama's server.log, parses entries
and broadcasts them over WebSocket. Keeps a bounded in-memory ring buffer.
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

from app.config import Config
from app.services.websocket_manager import websocket_manager

logger = logging.getLogger(__name__)

MAX_BUFFER = 1000


class LogManager:
    def __init__(self, config: Config, websocket_manager) -> None:
        self.config = config
        self.websocket_manager = websocket_manager
        self.running = False
        self.buffer: List[Dict[str, Any]] = []
        self._positions: Dict[str, int] = {}

    def _emit(self, entry: Dict[str, Any]) -> None:
        self.buffer.append(entry)
        if len(self.buffer) > MAX_BUFFER:
            self.buffer = self.buffer[-MAX_BUFFER:]

    async def _tail(self, path: str, source: str) -> None:
        """Read new lines from a log file since the last position."""
        if not os.path.exists(path):
            return
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                f.seek(self._positions.get(path, 0))
                lines = f.readlines()
                self._positions[path] = f.tell()
        except Exception as e:
            logger.debug("Cannot read log %s: %s", path, e)
            return

        for raw in lines:
            line = raw.rstrip("\n")
            if not line.strip():
                continue
            entry = self._parse_line(line, source)
            self._emit(entry)
            await self.websocket_manager.send_event("log_entry", entry)

    def _parse_line(self, line: str, source: str) -> Dict[str, Any]:
        # Common formats: "2024-10-13 14:45:32.123 INFO  message" or "... LEVEL message".
        parts = line.split(None, 3)
        level = "INFO"
        message = line
        timestamp = datetime.utcnow().isoformat()
        if len(parts) >= 3:
            ts_str = f"{parts[0]} {parts[1]}"
            for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
                try:
                    timestamp = datetime.strptime(ts_str, fmt).isoformat()
                    break
                except ValueError:
                    continue
            if parts[2].upper() in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"):
                level = parts[2].upper()
                message = parts[3] if len(parts) > 3 else ""
        return {
            "timestamp": timestamp,
            "level": level,
            "message": message[:2000],
            "source": source,
        }

    async def run(self) -> None:
        log_dir = os.path.join(os.path.dirname(__file__), "..", "..", "logs")
        app_log = os.path.abspath(os.path.join(log_dir, "ollama_monitor.log"))
        ollama_log = os.path.abspath(os.path.join(log_dir, "ollama", "server.log"))
        while self.running:
            try:
                await self._tail(app_log, "OllamaMonitor")
                await self._tail(ollama_log, "Ollama")
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Error in log monitoring loop: %s", e)
            await asyncio.sleep(1)

    def get_recent_logs(self, limit: int = 100) -> List[Dict[str, Any]]:
        recent = self.buffer[-limit:]
        return list(reversed(recent))

    def get_logs(self, level: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
        logs = self.buffer[-limit:]
        if level:
            logs = [log for log in logs if log["level"].upper() == level.upper()]
        return list(reversed(logs))


async def start_monitoring() -> LogManager:
    global log_manager
    config = Config()
    from app.services.websocket_manager import websocket_manager as _ws
    log_manager = LogManager(config, _ws)
    log_manager.running = True
    return log_manager


async def run() -> None:
    global log_manager
    if log_manager is None:
        await start_monitoring()
    if log_manager:
        await log_manager.run()


async def stop_monitoring() -> None:
    global log_manager
    if log_manager:
        log_manager.running = False


log_manager: LogManager = None  # type: ignore[assignment]
