"""
Ollama Monitor - Universal monitoring system for a local Ollama server.

Run:  python main.py        (listens on 127.0.0.1:8881 by default)
"""

from __future__ import annotations

import asyncio
import logging
import logging.handlers
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes import router as api_router
from app.config import PROJECT_ROOT, load_config_from_yaml
from app.database import (
    Base,
    create_engine_from_config,
    create_session_factory,
    set_session_factory,
)
from app.monitoring import gpu as gpu_monitor
from app.monitoring import logs as logs_monitor
from app.monitoring import ollama as ollama_monitor
from app.monitoring import system as system_monitor
from app.proxy.router import router as proxy_router
from app.services.request_tracker import request_tracker
import app.services.websocket_manager as ws_module
from app.services.websocket_manager import WebSocketManager

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(name)s: %(message)s")
logger = logging.getLogger("ollama_monitor")

TEMPLATES_DIR = PROJECT_ROOT / "app" / "templates"
STATIC_DIR = PROJECT_ROOT / "app" / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: startup / shutdown."""
    config = load_config_from_yaml()
    config.ensure_paths()

    if not config.validate_port_availability():
        logger.error(
            "Port %s:%s is already in use. Free the port or change server_port in config.yaml.",
            config.server_host,
            config.server_port,
        )

    # Configure file logging.
    log_path = PROJECT_ROOT / "logs" / "ollama_monitor.log"
    file_handler = logging.handlers.RotatingFileHandler(
        log_path, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    file_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s"))
    logging.getLogger().addHandler(file_handler)

    # Database.
    engine = await create_engine_from_config(config)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = await create_session_factory(engine)
    set_session_factory(session_factory)

    # WebSocket manager (module-level singleton).
    ws = WebSocketManager()
    ws_module.websocket_manager = ws

    # State for request handlers.
    app.state.config = config
    app.state.db_engine = engine
    app.state.db_session = session_factory
    app.state.websocket_manager = ws
    app.state.started_at = __import__("datetime").datetime.utcnow()

    # Mark requests from a previous run as INTERRUPTED.
    await request_tracker.mark_interrupted_on_startup()

    # Start monitoring background tasks.
    tasks: list[asyncio.Task] = []
    if config.monitoring_passive_enabled:
        try:
            await ollama_monitor.start_monitoring()
            tasks.append(asyncio.create_task(ollama_monitor.run(), name="ollama-monitor"))
        except Exception as e:
            logger.error("Failed to start Ollama monitoring: %s", e)
        try:
            await system_monitor.start_monitoring()
            tasks.append(asyncio.create_task(system_monitor.run(), name="system-monitor"))
        except Exception as e:
            logger.error("Failed to start system monitoring: %s", e)
        try:
            await logs_monitor.start_monitoring()
            tasks.append(asyncio.create_task(logs_monitor.run(), name="logs-monitor"))
        except Exception as e:
            logger.error("Failed to start log monitoring: %s", e)
    try:
        await gpu_monitor.start_monitoring()
        tasks.append(asyncio.create_task(gpu_monitor.run(), name="gpu-monitor"))
    except Exception as e:
        logger.error("Failed to start GPU monitoring: %s", e)

    app.state.monitor_tasks = tasks
    logger.info("Ollama Monitor started on http://%s:%s", config.server_host, config.server_port)
    yield

    # Shutdown.
    logger.info("Shutting down Ollama Monitor...")
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    await ws.shutdown()
    await engine.dispose()
    logger.info("Ollama Monitor shutdown complete")


app = FastAPI(
    title="Ollama Monitor",
    description="Universal monitoring system for local Ollama server",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# API + proxy routers.
app.include_router(api_router)
app.include_router(proxy_router)


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "message": "Ollama Monitor is running"}


@app.websocket("/ws/monitor")
async def ws_monitor(websocket: WebSocket):
    """WebSocket endpoint for live monitoring events."""
    await ws_module.websocket_manager.connect(websocket)
    try:
        while True:
            try:
                await websocket.receive_text()
            except WebSocketDisconnect:
                break
    finally:
        await ws_module.websocket_manager.disconnect(websocket)


@app.get("/")
async def index():
    """Serve the single-page web UI."""
    return FileResponse(TEMPLATES_DIR / "index.html")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


if __name__ == "__main__":
    import uvicorn

    config = load_config_from_yaml()
    uvicorn.run(
        "main:app",
        host=config.server_host,
        port=config.server_port,
        reload=False,
        log_level="info",
    )
