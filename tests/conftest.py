"""
Pytest fixtures for Ollama Monitor tests.

Adds the project root to sys.path and prepares an isolated in-memory DB
with the session factory wired for the request tracker.
"""

from __future__ import annotations

import os
import sys

import pytest
import pytest_asyncio

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base, set_session_factory
from app.config import Config


@pytest.fixture(scope="session")
def anyio_backend():
    return "asyncio"


@pytest_asyncio.fixture
async def db_session_factory():
    """Create an isolated in-memory async DB and register the session factory."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = sessionmaker(engine, class_=__import__("sqlalchemy.ext.asyncio", fromlist=["AsyncSession"]).AsyncSession, expire_on_commit=False)
    set_session_factory(factory)
    yield factory
    await engine.dispose()


@pytest.fixture
def config():
    return Config(
        server_host="127.0.0.1",
        server_port=18881,
        ollama_base_url="http://127.0.0.1:11434",
        database_path="data/test_ollama_monitor.db",
    )
