"""
Database models and initialization for Ollama Monitor.

Uses SQLAlchemy 2.x async (aiosqlite). Tables are created via the application
lifespan (see main.py) instead of at import time to avoid blocking the event loop.
SQLite runs in WAL mode and an in-memory connection pool is used because SQLite
does not support the standard queue pool well under async concurrency.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import AsyncGenerator, Optional
from uuid import uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    event,
    func,
)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import declarative_base, relationship

logger = logging.getLogger(__name__)

Base = declarative_base()


def _uuid() -> str:
    return str(uuid4())


class Request(Base):
    """History of a single (proxied or passive) HTTP request."""

    __tablename__ = "requests"

    id = Column(String(36), primary_key=True, default=_uuid)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    client_ip = Column(String(45), nullable=True)
    client_port = Column(Integer, nullable=True)
    method = Column(String(10), nullable=False)
    endpoint = Column(String(255), nullable=False)
    model_name = Column(String(255), nullable=True, index=True)
    operation_type = Column(String(50), nullable=False, index=True)
    http_status = Column(Integer, nullable=False)
    execution_status = Column(String(20), nullable=False, index=True)
    request_size = Column(Integer, nullable=True)
    response_size = Column(Integer, nullable=True)
    user_agent = Column(Text, nullable=True)
    client_name = Column(String(100), nullable=True, index=True)
    monitoring_mode = Column(String(10), nullable=False)
    data_source = Column(String(50), nullable=False)
    session_id = Column(String(100), nullable=True, index=True)
    error_message = Column(Text, nullable=True)

    # Timing metrics (all in milliseconds, unless *_duration which come from
    # Ollama in nanoseconds and are stored as returned).
    total_duration = Column(Integer, nullable=True)  # ms, wall-clock measured by proxy
    model_load_duration = Column(Integer, nullable=True)  # ns from Ollama
    prompt_eval_duration = Column(Integer, nullable=True)  # ns from Ollama
    eval_duration = Column(Integer, nullable=True)  # ns from Ollama
    first_byte_time = Column(Integer, nullable=True)  # ms
    first_token_time = Column(Integer, nullable=True)  # ms
    response_transfer_time = Column(Integer, nullable=True)  # ms

    # Token metrics
    prompt_eval_count = Column(Integer, nullable=True)
    eval_count = Column(Integer, nullable=True)
    total_tokens = Column(Integer, nullable=True)
    output_tokens = Column(Integer, nullable=True)

    # Generation speeds (tokens per second), computed from Ollama timings.
    generation_speed = Column(Float, nullable=True)
    prompt_processing_speed = Column(Float, nullable=True)

    gpu_metrics = relationship("GpuMetric", back_populates="request")
    system_events = relationship("SystemEvent", back_populates="request")
    model = relationship(
        "Model",
        primaryjoin="Request.model_name == Model.name",
        foreign_keys="[Request.model_name]",
        viewonly=True,
    )
    client = relationship(
        "Client",
        primaryjoin="Request.client_ip == Client.client_ip",
        foreign_keys="[Request.client_ip]",
        viewonly=True,
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "client_ip": self.client_ip,
            "client_port": self.client_port,
            "method": self.method,
            "endpoint": self.endpoint,
            "model_name": self.model_name,
            "operation_type": self.operation_type,
            "http_status": self.http_status,
            "execution_status": self.execution_status,
            "request_size": self.request_size,
            "response_size": self.response_size,
            "user_agent": self.user_agent,
            "client_name": self.client_name,
            "monitoring_mode": self.monitoring_mode,
            "data_source": self.data_source,
            "session_id": self.session_id,
            "error_message": self.error_message,
            "total_duration": self.total_duration,
            "model_load_duration": self.model_load_duration,
            "prompt_eval_duration": self.prompt_eval_duration,
            "eval_duration": self.eval_duration,
            "first_byte_time": self.first_byte_time,
            "first_token_time": self.first_token_time,
            "response_transfer_time": self.response_transfer_time,
            "prompt_eval_count": self.prompt_eval_count,
            "eval_count": self.eval_count,
            "total_tokens": self.total_tokens,
            "output_tokens": self.output_tokens,
            "generation_speed": self.generation_speed,
            "prompt_processing_speed": self.prompt_processing_speed,
        }


class Model(Base):
    """Information about an Ollama model."""

    __tablename__ = "models"

    id = Column(String(36), primary_key=True, default=_uuid)
    name = Column(String(255), unique=True, nullable=False)
    size = Column(Integer, nullable=True)  # bytes
    gpu_memory_size = Column(Integer, nullable=True)  # bytes (size_vram from /api/ps)
    context_length = Column(Integer, nullable=True)
    quantization_type = Column(String(50), nullable=True)
    last_loaded = Column(DateTime, nullable=True)
    last_unloaded = Column(DateTime, nullable=True)
    total_requests = Column(Integer, default=0)
    average_generation_speed = Column(Float, nullable=True)
    average_prompt_processing_speed = Column(Float, nullable=True)
    average_response_time = Column(Integer, nullable=True)  # ms
    total_input_tokens = Column(Integer, default=0)
    total_output_tokens = Column(Integer, default=0)
    total_errors = Column(Integer, default=0)

    requests = relationship(
        "Request",
        primaryjoin="Model.name == Request.model_name",
        foreign_keys="[Request.model_name]",
        viewonly=True,
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "size": self.size,
            "gpu_memory_size": self.gpu_memory_size,
            "context_length": self.context_length,
            "quantization_type": self.quantization_type,
            "last_loaded": self.last_loaded.isoformat() if self.last_loaded else None,
            "last_unloaded": self.last_unloaded.isoformat() if self.last_unloaded else None,
            "total_requests": self.total_requests,
            "average_generation_speed": self.average_generation_speed,
            "average_prompt_processing_speed": self.average_prompt_processing_speed,
            "average_response_time": self.average_response_time,
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "total_errors": self.total_errors,
        }


class Client(Base):
    """Information about a client application."""

    __tablename__ = "clients"

    id = Column(String(36), primary_key=True, default=_uuid)
    client_ip = Column(String(45), nullable=False, index=True)
    client_name = Column(String(100), nullable=True)
    user_agent = Column(Text, nullable=True)
    total_requests = Column(Integer, default=0)
    last_active = Column(DateTime, default=datetime.utcnow, nullable=False)
    total_request_duration = Column(Integer, default=0)  # ms
    average_response_time = Column(Integer, nullable=True)  # ms
    used_models = Column(JSON, default=list)

    requests = relationship(
        "Request",
        primaryjoin="Client.client_ip == Request.client_ip",
        foreign_keys="[Request.client_ip]",
        viewonly=True,
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "client_ip": self.client_ip,
            "client_name": self.client_name,
            "user_agent": self.user_agent,
            "total_requests": self.total_requests,
            "last_active": self.last_active.isoformat() if self.last_active else None,
            "total_request_duration": self.total_request_duration,
            "average_response_time": self.average_response_time,
            "used_models": self.used_models or [],
        }


class GpuMetric(Base):
    """A single GPU sample."""

    __tablename__ = "gpu_metrics"

    id = Column(String(36), primary_key=True, default=_uuid)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    gpu_index = Column(Integer, nullable=False)
    gpu_name = Column(String(255), nullable=False)
    gpu_uuid = Column(String(255), nullable=False)
    total_vram = Column(Integer, nullable=False)
    used_vram = Column(Integer, nullable=False)
    free_vram = Column(Integer, nullable=False)
    gpu_load = Column(Integer, nullable=False)
    memory_load = Column(Integer, nullable=True)
    temperature = Column(Integer, nullable=True)
    power_usage = Column(Integer, nullable=True)
    power_limit = Column(Integer, nullable=True)
    gpu_frequency = Column(Integer, nullable=True)
    memory_frequency = Column(Integer, nullable=True)
    request_id = Column(String(36), ForeignKey("requests.id"), nullable=True)

    request = relationship("Request", back_populates="gpu_metrics")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "gpu_index": self.gpu_index,
            "gpu_name": self.gpu_name,
            "gpu_uuid": self.gpu_uuid,
            "total_vram": self.total_vram,
            "used_vram": self.used_vram,
            "free_vram": self.free_vram,
            "gpu_load": self.gpu_load,
            "memory_load": self.memory_load,
            "temperature": self.temperature,
            "power_usage": self.power_usage,
            "power_limit": self.power_limit,
            "gpu_frequency": self.gpu_frequency,
            "memory_frequency": self.memory_frequency,
        }


class SystemEvent(Base):
    """System / application event shown on the Logs page."""

    __tablename__ = "system_events"

    id = Column(String(36), primary_key=True, default=_uuid)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    event_type = Column(String(50), nullable=False)  # status, error, warning, info
    message = Column(Text, nullable=False)
    source = Column(String(50), nullable=False)
    details = Column(JSON, nullable=True)
    request_id = Column(String(36), ForeignKey("requests.id"), nullable=True)

    request = relationship("Request", back_populates="system_events")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "event_type": self.event_type,
            "message": self.message,
            "source": self.source,
            "details": self.details,
        }


class Setting(Base):
    """Key/value application setting."""

    __tablename__ = "settings"

    id = Column(String(36), primary_key=True, default=_uuid)
    key = Column(String(255), unique=True, nullable=False)
    value = Column(Text, nullable=False)
    data_type = Column(String(50), nullable=False)  # string, int, float, boolean, json

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "key": self.key,
            "value": self.value,
            "data_type": self.data_type,
        }


# Composite indexes for fast filtered queries.
Index("ix_requests_created_status", Request.created_at, Request.execution_status)
Index("ix_requests_model_created", Request.model_name, Request.created_at)
Index("ix_requests_client_created", Request.client_ip, Request.created_at)
Index("ix_gpu_metrics_index_created", GpuMetric.gpu_index, GpuMetric.created_at)


def _set_sqlite_pragma(dbapi_connection, connection_record):
    """Enable WAL and foreign keys for SQLite."""
    try:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.close()
    except Exception:  # pragma: no cover - sqlite specific
        logger.debug("Could not set SQLite pragmas", exc_info=True)


async def create_engine_from_config(config) -> "AsyncEngine":
    """Create the async engine for the given config and apply SQLite pragmas."""
    database_url = config.get_database_url()
    engine = create_async_engine(database_url, echo=False, future=True)
    if database_url.startswith("sqlite"):
        event.listen(engine.sync_engine, "connect", _set_sqlite_pragma)
    return engine


async def create_session_factory(engine) -> async_sessionmaker:
    """Create a session factory bound to the engine."""
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


# Module-level session factory, set once by the application lifespan.
_session_factory: Optional[async_sessionmaker] = None


def set_session_factory(factory: async_sessionmaker) -> None:
    """Called by the application lifespan to register the session factory."""
    global _session_factory
    _session_factory = factory


async def get_session() -> AsyncSession:
    """Create a standalone async session for services (tracker, monitors)."""
    if _session_factory is None:
        raise RuntimeError("Database session factory not initialized (app not started)")
    return _session_factory()


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency yielding an async database session."""
    if _session_factory is None:
        raise RuntimeError("Database session factory not initialized (app not started)")
    async with _session_factory() as session:
        yield session
