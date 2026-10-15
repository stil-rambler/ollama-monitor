"""
API routes for Ollama Monitor - aggregates all API routers and adds
system/statistics endpoints.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from typing import Optional
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import Request as RequestModel, get_db
from app.monitoring import gpu as gpu_monitor
from app.monitoring import ollama as ollama_monitor
from app.monitoring import system as system_monitor
from app.proxy.streaming import analyze_stream_data
from app.services.request_tracker import request_tracker

from .dashboard import router as dashboard_router
from .gpu import router as gpu_router
from .requests import router as requests_router
from .models import router as models_router
from .clients import router as clients_router
from .settings import router as settings_router

router = APIRouter(prefix="/api")

router.include_router(dashboard_router)
router.include_router(requests_router)
router.include_router(models_router)
router.include_router(clients_router)
router.include_router(gpu_router)
router.include_router(settings_router)


@router.get("/status", tags=["system"])
async def system_status(request: Request):
    """Overall system status: Ollama, GPU, system, active requests."""
    ws = request.app.state.websocket_manager
    gpu_summary = []
    try:
        gpu_summary = await gpu_monitor.gpu_monitor.collect_all()
    except Exception:
        pass

    ollama_status = getattr(ollama_monitor.ollama_monitor, "last_status", {"status": "unknown"})
    sys_metrics = {}
    try:
        sys_metrics = await system_monitor.system_monitor.get_system_metrics()
    except Exception:
        pass

    return {
        "ollama": ollama_status,
        "gpu": gpu_summary,
        "system": sys_metrics,
        "active_requests": len(request_tracker.running_requests),
        "websocket": {
            "connections": getattr(ws, "_stats", {}).get("current_connections", 0),
            "total_events": getattr(ws, "_stats", {}).get("total_events", 0),
        },
    }


@router.get("/statistics", tags=["statistics"])
async def overall_statistics(db: AsyncSession = Depends(get_db)):
    """Aggregated statistics across all requests."""
    total = (await db.execute(select(func.count(RequestModel.id)))).scalar_one()
    completed = (
        await db.execute(
            select(func.count(RequestModel.id)).where(RequestModel.execution_status == "COMPLETED")
        )
    ).scalar_one()
    errors = (
        await db.execute(
            select(func.count(RequestModel.id)).where(RequestModel.execution_status == "ERROR")
        )
    ).scalar_one()
    total_tokens = (
        await db.execute(
            select(func.coalesce(func.sum(RequestModel.prompt_eval_count), 0) + func.coalesce(func.sum(RequestModel.eval_count), 0))
        )
    ).scalar_one()
    output_tokens = (
        await db.execute(select(func.coalesce(func.sum(RequestModel.eval_count), 0)))
    ).scalar_one()

    # Average generation speed across completed requests.
    avg_speed = (
        await db.execute(
            select(func.avg(RequestModel.generation_speed)).where(
                RequestModel.execution_status == "COMPLETED",
                RequestModel.generation_speed.isnot(None),
            )
        )
    ).scalar_one()

    return {
        "total_requests": total,
        "completed_requests": completed,
        "error_requests": errors,
        "total_tokens": int(total_tokens or 0),
        "total_output_tokens": int(output_tokens or 0),
        "average_generation_speed": round(float(avg_speed), 2) if avg_speed else 0.0,
    }


@router.get("/active_requests", tags=["statistics"])
async def active_requests():
    """Currently running requests tracked by the proxy."""
    return request_tracker.get_running()


@router.get("/logs", tags=["logs"])
async def get_logs(
    level: Optional[str] = None,
    limit: int = Query(100, ge=1, le=500),
):
    """Recent application/Ollama log entries from the in-memory buffer."""
    from app.monitoring.logs import log_manager
    if log_manager is None:
        return []
    return log_manager.get_logs(level=level, limit=limit)


@router.get("/config", tags=["system"])
async def get_config(request: Request):
    """Current effective configuration (auth token masked)."""
    cfg = request.app.state.config
    return {
        "server_host": cfg.server_host,
        "server_port": cfg.server_port,
        "ollama_base_url": cfg.ollama_base_url,
        "monitoring_passive_enabled": cfg.monitoring_passive_enabled,
        "monitoring_proxy_enabled": cfg.monitoring_proxy_enabled,
        "monitoring_gpu_interval": cfg.monitoring_gpu_interval,
        "monitoring_ollama_interval": cfg.monitoring_ollama_interval,
        "database_path": cfg.database_path,
        "retention_requests_days": cfg.retention_requests_days,
        "retention_gpu_raw_hours": cfg.retention_gpu_raw_hours,
        "retention_gpu_aggregated_days": cfg.retention_gpu_aggregated_days,
        "logging_level": cfg.logging_level,
        "ui_language": cfg.ui_language,
        "ui_theme": cfg.ui_theme,
    }
