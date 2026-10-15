"""
GPU monitoring for Ollama Monitor.

Uses NVML (nvidia-ml-py) as the primary source and nvidia-smi as a fallback.
The system continues to work when no NVIDIA GPU is present.
"""

from __future__ import annotations

import asyncio
import logging
import subprocess
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import uuid4

from app.config import Config
from app.database import GpuMetric, get_session
from app.services.websocket_manager import websocket_manager

logger = logging.getLogger(__name__)

try:  # pragma: no cover - hardware dependent
    import pynvml

    NVML_AVAILABLE = True
except Exception:  # pragma: no cover
    NVML_AVAILABLE = False


def _fallback_nvidia_smi() -> List[Dict[str, Any]]:
    """Query nvidia-smi in CSV mode as a fallback when NVML is unavailable."""
    gpus: List[Dict[str, Any]] = []
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=index,name,uuid,memory.total,memory.used,memory.free,utilization.gpu,utilization.memory,temperature.gpu,power.draw,power.limit,clocks.gr,clocks.mem",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            return gpus
        for line in result.stdout.strip().splitlines():
            parts = [p.strip() for p in line.split(",")]
            if len(parts) < 8:
                continue
            try:
                total = int(parts[3]) * 1024 * 1024  # MiB -> bytes
                used = int(parts[4]) * 1024 * 1024
                free = int(parts[5]) * 1024 * 1024
                gpus.append(
                    {
                        "gpu_index": int(parts[0]),
                        "gpu_name": parts[1],
                        "gpu_uuid": parts[2],
                        "total_vram": total,
                        "used_vram": used,
                        "free_vram": free,
                        "gpu_load": int(parts[6]),
                        "memory_load": int(parts[7]),
                        "temperature": int(parts[8]) if parts[8] != "N/A" else None,
                        "power_usage": int(float(parts[9])) if parts[9] != "N/A" else None,
                        "power_limit": int(float(parts[10])) if parts[10] != "N/A" else None,
                        "gpu_frequency": int(parts[11]) if parts[11] != "N/A" else None,
                        "memory_frequency": int(parts[12]) if len(parts) > 12 and parts[12] != "N/A" else None,
                    }
                )
            except (ValueError, IndexError):
                continue
    except Exception as e:
        logger.debug("nvidia-smi fallback failed: %s", e)
    return gpus


class GpuMonitor:
    def __init__(self, config: Config, websocket_manager) -> None:
        self.config = config
        self.websocket_manager = websocket_manager
        self.running = False
        self.gpu_handles: list = []
        self.gpu_names: Dict[int, str] = {}
        self.gpu_uuids: Dict[int, str] = {}
        self.use_nvml = NVML_AVAILABLE

    async def initialize(self) -> None:
        """Discover GPUs (NVML or nvidia-smi fallback)."""
        if self.use_nvml:
            try:
                pynvml.nvmlInit()
                count = pynvml.nvmlDeviceGetCount()
                for i in range(count):
                    handle = pynvml.nvmlDeviceGetHandleByIndex(i)
                    self.gpu_handles.append(handle)
                    self.gpu_names[i] = pynvml.nvmlDeviceGetName(handle)
                    self.gpu_uuids[i] = pynvml.nvmlDeviceGetUUID(handle)
                logger.info("NVML initialized: %d GPU(s) found", count)
                return
            except Exception as e:
                logger.warning("NVML init failed (%s); falling back to nvidia-smi", e)
                self.use_nvml = False
                try:
                    pynvml.nvmlShutdown()
                except Exception:
                    pass

        # Fallback: discover via nvidia-smi.
        gpus = _fallback_nvidia_smi()
        for gpu in gpus:
            self.gpu_names[gpu["gpu_index"]] = gpu["gpu_name"]
            self.gpu_uuids[gpu["gpu_index"]] = gpu["gpu_uuid"]
        logger.info("GPU discovery via nvidia-smi: %d GPU(s)", len(gpus))

    async def get_gpu_metrics(self, index: int) -> Optional[Dict[str, Any]]:
        """Collect a single GPU sample."""
        if self.use_nvml and index < len(self.gpu_handles):
            try:
                handle = self.gpu_handles[index]
                mem = pynvml.nvmlDeviceGetMemoryInfo(handle)
                util = pynvml.nvmlDeviceGetUtilizationRates(handle)
                metrics: Dict[str, Any] = {
                    "gpu_index": index,
                    "gpu_name": self.gpu_names.get(index, "Unknown"),
                    "gpu_uuid": self.gpu_uuids.get(index, "Unknown"),
                    "total_vram": mem.total,
                    "used_vram": mem.used,
                    "free_vram": mem.free,
                    "gpu_load": util.gpu,
                    "memory_load": util.memory,
                    "temperature": None,
                    "power_usage": None,
                    "power_limit": None,
                    "gpu_frequency": None,
                    "memory_frequency": None,
                }
                try:
                    metrics["temperature"] = pynvml.nvmlDeviceGetTemperature(
                        handle, pynvml.NVML_TEMPERATURE_GPU
                    )
                except Exception:
                    pass
                try:
                    metrics["power_usage"] = int(pynvml.nvmlDeviceGetPowerUsage(handle) / 1000)
                except Exception:
                    pass
                try:
                    metrics["power_limit"] = int(pynvml.nvmlDeviceGetPowerLimit(handle) / 1000)
                except Exception:
                    pass
                try:
                    metrics["gpu_frequency"] = pynvml.nvmlDeviceGetClockInfo(handle, pynvml.NVML_CLOCK_GRAPHICS)
                except Exception:
                    pass
                try:
                    metrics["memory_frequency"] = pynvml.nvmlDeviceGetClockInfo(handle, pynvml.NVML_CLOCK_MEM)
                except Exception:
                    pass
                return metrics
            except Exception as e:
                logger.debug("NVML metrics failed for GPU %s: %s", index, e)
                return None

        # Fallback to nvidia-smi.
        gpus = _fallback_nvidia_smi()
        for gpu in gpus:
            if gpu["gpu_index"] == index:
                return gpu
        return None

    async def collect_all(self) -> List[Dict[str, Any]]:
        """Collect metrics for every known GPU."""
        metrics: List[Dict[str, Any]] = []
        if self.use_nvml:
            indexes = list(range(len(self.gpu_handles)))
        else:
            indexes = sorted(self.gpu_names.keys())
        for idx in indexes:
            m = await self.get_gpu_metrics(idx)
            if m:
                metrics.append(m)
        return metrics

    async def save_metric(self, gpu_info: Dict[str, Any]) -> None:
        try:
            async with await get_session() as session:
                session.add(
                    GpuMetric(
                        id=str(uuid4()),
                        created_at=datetime.utcnow(),
                        gpu_index=gpu_info["gpu_index"],
                        gpu_name=gpu_info["gpu_name"],
                        gpu_uuid=gpu_info["gpu_uuid"],
                        total_vram=gpu_info["total_vram"],
                        used_vram=gpu_info["used_vram"],
                        free_vram=gpu_info["free_vram"],
                        gpu_load=gpu_info["gpu_load"],
                        memory_load=gpu_info.get("memory_load"),
                        temperature=gpu_info.get("temperature"),
                        power_usage=gpu_info.get("power_usage"),
                        power_limit=gpu_info.get("power_limit"),
                        gpu_frequency=gpu_info.get("gpu_frequency"),
                        memory_frequency=gpu_info.get("memory_frequency"),
                    )
                )
                await session.commit()
        except Exception as e:
            logger.error("Error saving GPU metric: %s", e)

    async def run(self) -> None:
        """Monitoring loop: sample every interval and broadcast."""
        while self.running:
            try:
                metrics = await self.collect_all()
                for m in metrics:
                    await self.save_metric(m)
                if metrics:
                    await self.websocket_manager.send_event("gpu_updated", metrics)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Error in GPU monitoring loop: %s", e)
            await asyncio.sleep(self.config.monitoring_gpu_interval)


async def start_monitoring() -> GpuMonitor:
    global gpu_monitor
    config = Config()
    from app.services.websocket_manager import websocket_manager as _ws
    gpu_monitor = GpuMonitor(config, _ws)
    await gpu_monitor.initialize()
    gpu_monitor.running = True
    return gpu_monitor


async def run() -> None:
    global gpu_monitor
    if gpu_monitor is None:
        await start_monitoring()
    if gpu_monitor:
        await gpu_monitor.run()


async def stop_monitoring() -> None:
    global gpu_monitor
    if gpu_monitor:
        gpu_monitor.running = False


gpu_monitor: Optional[GpuMonitor] = None
