"""
Integration test for the transparent proxy with a mocked upstream.
No real Ollama required.
"""

from __future__ import annotations

import json

import httpx
import pytest
from fastapi import FastAPI


class FakeUpstream(httpx.MockTransport):
    """Responds as a minimal Ollama server."""

    def __init__(self):
        self.last_path = None
        self.last_json = None
        super().__init__(self._handler)

    async def _handler(self, request: httpx.Request) -> httpx.Response:
        self.last_path = request.url.path
        if request.content:
            try:
                self.last_json = json.loads(request.content)
            except Exception:
                self.last_json = None
        if request.url.path == "/api/chat" and self.last_json and self.last_json.get("stream"):
            body = (
                '{"model":"m","response":"hel","done":false}\n'
                '{"model":"m","response":"lo","done":false}\n'
                '{"model":"m","response":"","done":true,"eval_count":5,"prompt_eval_count":3,"eval_duration":1000000000,"prompt_eval_duration":100000000,"total_duration":2000000000}\n'
            )
            return httpx.Response(200, content=body, headers={"Content-Type": "application/x-ndjson"})
        if request.url.path == "/api/chat":
            return httpx.Response(
                200,
                json={
                    "model": "m",
                    "message": {"role": "assistant", "content": "ok"},
                    "done": True,
                    "eval_count": 5,
                    "prompt_eval_count": 3,
                    "eval_duration": 1000000000,
                    "prompt_eval_duration": 100000000,
                },
            )
        if request.url.path == "/api/version":
            return httpx.Response(200, json={"version": "0.40.0"})
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": "m", "size": 100}]})
        return httpx.Response(404, json={"error": "not found"})


@pytest.fixture
def fake_upstream():
    return FakeUpstream()


@pytest.fixture
def proxy_app(fake_upstream, db_session_factory):
    from app.proxy.router import http_client, router as proxy_router
    from app.services.websocket_manager import WebSocketManager

    # Swap the shared upstream transport with the mock.
    http_client._transport = fake_upstream
    http_client._transport._pool = None

    app = FastAPI()
    app.state.websocket_manager = WebSocketManager()
    app.include_router(proxy_router)
    return app


@pytest.fixture
async def client(proxy_app):
    transport = httpx.ASGITransport(app=proxy_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.mark.asyncio
async def test_health_via_proxy_fake(client):
    r = await client.get("/api/version")
    assert r.status_code == 200
    assert r.json()["version"] == "0.40.0"


@pytest.mark.asyncio
async def test_non_streaming_chat(client, db_session_factory):
    from app.services.request_tracker import request_tracker
    r = await client.post(
        "/api/chat",
        json={"model": "m", "messages": [{"role": "user", "content": "hi"}], "stream": False},
    )
    assert r.status_code == 200
    assert r.json()["message"]["content"] == "ok"
    assert len(request_tracker.completed_requests) >= 1
    req = list(request_tracker.completed_requests.values())[-1]
    assert req.execution_status == "COMPLETED"
    assert req.eval_count == 5


@pytest.mark.asyncio
async def test_streaming_chat(client, db_session_factory):
    from app.services.request_tracker import request_tracker
    r = await client.post(
        "/api/chat",
        json={"model": "m", "messages": [{"role": "user", "content": "hi"}], "stream": True},
    )
    assert r.status_code == 200
    assert "done" in r.text
    reqs = [x for x in request_tracker.completed_requests.values()]
    assert any(x.execution_status == "COMPLETED" and x.eval_count == 5 for x in reqs)
