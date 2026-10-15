"""
System monitoring for Ollama Monitor (CPU, RAM, disk, processes via psutil).
"""

from __future__ import annotations

import asyncio
import logging
import platform
from datetime import datetime
from typing import Any, Dict

import psutil

from app.config import Config
from app.services.websocket_manager import websocket_manager

logger = logging.getLogger(__name__)


class SystemMonitor:
    def __init__(self, config: Config, websocket_manager) -> None:
        self.config = config
        self.websocket_manager = websocket_manager
        self.running = False

    async def get_system_metrics(self) -> Dict[str, Any]:
        metrics: Dict[str, Any] = {"timestamp": datetime.utcnow().isoformat()}
        try:
            metrics["cpu_usage"] = psutil.cpu_percent(interval=None)
            metrics["cpu_count"] = psutil.cpu_count()
            mem = psutil.virtual_memory()
            metrics["memory_total"] = mem.total
            metrics["memory_available"] = mem.available
            metrics["memory_used"] = mem.used
            metrics["memory_percent"] = mem.percent
            try:
                disk = psutil.disk_usage("/")
                metrics["disk_total"] = disk.total
                metrics["disk_used"] = disk.used
                metrics["disk_free"] = disk.free
                metrics["disk_percent"] = disk.percent
            except Exception:
                pass

            # Ollama process memory.
            ollama_rss = None
            for proc in psutil.process_iter(["pid", "name"]):
                try:
                    if "ollama" in (proc.info["name"] or "").lower():
                        ollama_rss = proc.memory_info().rss
                        break
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                    continue
            metrics["ollama_memory"] = ollama_rss

            # Own process memory.
            try:
                metrics["monitor_memory"] = psutil.Process().memory_info().rss
            except Exception:
                metrics["monitor_memory"] = None

            metrics["platform"] = platform.platform()
            metrics["python_version"] = platform.python_version()
        except Exception as e:
            logger.error("Error collecting system metrics: %s", e)
        return metrics

    async def run(self) -> None:
        while self.running:
            try:
                metrics = await self.get_system_metrics()
                await self.websocket_manager.send_event("system_status_updated", metrics)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Error in system monitoring loop: %s", e)
            await asyncio.sleep(5)


async def start_monitoring() -> SystemMonitor:
    global system_monitor
    config = Config()
    from app.services.websocket_manager import websocket_manager as _ws
    system_monitor = SystemMonitor(config, _ws)
    system_monitor.running = True
    return system_monitor


async def run() -> None:
    global system_monitor
    if system_monitor is None:
        await start_monitoring()
    if system_monitor:
        await system_monitor.run()


async def stop_monitoring() -> None:
    global system_monitor
    if system_monitor:
        system_monitor.running = False


system_monitor: SystemMonitor = None  # type: ignore[assignment]
