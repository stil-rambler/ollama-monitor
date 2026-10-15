"""
Transparent proxy for the Ollama API and the OpenAI-compatible endpoints.

All requests arriving at /api/* and /v1/* are forwarded to the upstream Ollama
server. Streaming (NDJSON / SSE) responses are relayed chunk-by-chunk without
buffering the whole body; statistics are extracted in parallel from the stream
and persisted by the RequestTracker.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Optional

import httpx
from fastapi import APIRouter, Request, Response
from fastapi.responses import StreamingResponse

from app.config import Config
from app.proxy.streaming import StreamParser, analyze_stream_data
from app.services.request_tracker import request_tracker
from app.services.websocket_manager import WebSocketManager

logger = logging.getLogger(__name__)

router = APIRouter(tags=["proxy"])

config = Config()

# Shared upstream client reused across requests (connection pooling).
http_client = httpx.AsyncClient(
    timeout=httpx.Timeout(config.ollama_timeout, connect=10.0),
    follow_redirects=True,
)

# Headers that must not be forwarded upstream.
HOP_BY_HOP_HEADERS = {
    "host",
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
    "content-length",
    "content-encoding",
}

# Endpoints that are not request-oriented (no body / pure management) and for
# which we do not create a per-request history row.
NON_TRACKED_ENDPOINTS = {"/api/tags", "/api/version", "/api/ps"}


def _make_upstream_url(path: str, query: str = "") -> str:
    base = config.ollama_base_url.rstrip("/")
    return f"{base}{path}" + (f"?{query}" if query else "")


async def _read_json_body(request: Request) -> Optional[dict]:
    """Read and parse the request body as JSON when present."""
    try:
        body = await request.body()
    except Exception:
        body = b""
    if not body:
        return None
    try:
        return json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None


def _extract_client_name(request: Request) -> str:
    header = request.headers.get("X-Ollama-Monitor-Client")
    if header:
        return header.strip()
    ua = (request.headers.get("User-Agent") or "").lower()
    if "opencode" in ua:
        return "OpenCode"
    if "vs code" in ua or "visual studio code" in ua or "vscode" in ua:
        return "VSCode"
    if "python" in ua or "httpx" in ua or "openai" in ua:
        return "PythonScript"
    if "lmstudio" in ua:
        return "LMStudioClient"
    if "ollama" in ua:
        return "OllamaClient"
    if "cursor" in ua:
        return "Cursor"
    if "claude" in ua:
        return "Claude"
    if "mozilla" in ua or "chrome" in ua or "safari" in ua or "firefox" in ua or "edg/" in ua:
        return "Browser"
    if ua:
        return ua[:60]
    return "Unknown Client"


def _get_client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _prepare_headers(request: Request) -> dict:
    headers = {}
    for key, value in request.headers.items():
        if key.lower() in HOP_BY_HOP_HEADERS:
            continue
        headers[key] = value
    headers.pop("X-Ollama-Monitor-Proxy", None)
    return headers


@router.api_route(
    "/api/{path:path}",
    methods=["GET", "POST", "PUT", "DELETE", "PATCH"],
)
async def proxy_api(request: Request, path: str):
    return await proxy_request(request, f"/api/{path}")


@router.api_route(
    "/v1/{path:path}",
    methods=["GET", "POST", "PUT", "DELETE", "PATCH"],
)
async def proxy_v1(request: Request, path: str):
    return await proxy_request(request, f"/v1/{path}")


async def proxy_request(request: Request, path: str):
    """Generic transparent proxy for any upstream path."""
    # Guard against recursive proxying back onto ourselves.
    host = request.headers.get("X-Ollama-Monitor-Proxy")
    if host == "true":
        return Response(
            content=json.dumps({"error": "Recursive proxy request detected"}),
            media_type="application/json",
            status_code=400,
        )

    client_ip = _get_client_ip(request)
    client_port = request.client.port if request.client else None
    client_name = _extract_client_name(request)
    session_id = request.headers.get("X-Ollama-Monitor-Session")
    user_agent = request.headers.get("User-Agent", "")

    body = await _read_json_body(request)
    method = request.method
    query_params = dict(request.query_params)
    query_str = request.url.query

    websocket_manager: WebSocketManager = request.app.state.websocket_manager

    track = path not in NON_TRACKED_ENDPOINTS
    request_id = None
    if track:
        request_id = await request_tracker.start_request(
            client_ip=client_ip,
            client_port=client_port,
            client_name=client_name,
            method=method,
            endpoint=path,
            query_params=query_params,
            request_body=body,
            request_headers=dict(request.headers),
            monitoring_mode="proxy",
            session_id=session_id,
        )
        await websocket_manager.send_event(
            "request_started",
            {"id": request_id, "client": client_name, "model": body.get("model") if body else None, "endpoint": path},
        )

    headers = _prepare_headers(request)
    headers["X-Ollama-Monitor-Proxy"] = "true"
    upstream_url = _make_upstream_url(path, query_str)

    try:
        upstream_request = http_client.build_request(
            method=method,
            url=upstream_url,
            json=body if body is not None else None,
            headers=headers,
        )
        upstream = await http_client.send(upstream_request, stream=True)
    except httpx.RequestError as e:
        if request_id:
            await request_tracker.error_request(request_id, f"Upstream request failed: {e}", 502)
            await websocket_manager.send_event("request_failed", {"id": request_id, "error": str(e)})
        return Response(
            content=json.dumps({"error": f"Upstream Ollama request failed: {e}"}),
            media_type="application/json",
            status_code=502,
        )

    content_type = upstream.headers.get("Content-Type", "")
    is_stream = upstream.status_code < 400 and (
        "text/event-stream" in content_type
        or "application/x-ndjson" in content_type
        or content_type == "application/json" and body is not None and bool(body.get("stream"))
    )

    if request_id:
        await request_tracker.mark_first_byte(request_id)

    if upstream.status_code >= 400:
        # Error response - relay the body but record failure.
        error_body = b""
        try:
            async for chunk in upstream.aiter_bytes():
                error_body += chunk
        except Exception:
            pass
        if request_id:
            await request_tracker.error_request(
                request_id,
                f"Upstream returned {upstream.status_code}",
                upstream.status_code,
            )
            await websocket_manager.send_event(
                "request_failed",
                {"id": request_id, "status": upstream.status_code, "error": error_body[:500].decode("utf-8", "replace")},
            )
        return Response(
            content=error_body or b'{"error":"upstream error"}',
            media_type=content_type or "application/json",
            status_code=upstream.status_code,
        )

    # Build response headers (drop content-length: we stream and do not know it).
    resp_headers = {}
    for key, value in upstream.headers.items():
        if key.lower() in HOP_BY_HOP_HEADERS or key.lower() in ("content-length",):
            continue
        resp_headers[key] = value

    async def stream_generator():
        parser = StreamParser()
        finalized = False
        try:
            async for chunk in upstream.aiter_bytes():
                if not chunk:
                    continue
                yield chunk
                text = chunk.decode("utf-8", errors="replace")
                parser.update(text)
                # Analyze any complete JSON objects in the buffer.
                objs = parser.drain()
                for obj in objs:
                    analysis = await analyze_stream_data(obj, request_id) if request_id else {}
                    if analysis.get("done") and not finalized and request_id:
                        finalized = True
                if finalized and request_id:
                    await request_tracker.complete_request(request_id, "COMPLETED")
                    await websocket_manager.send_event("request_completed", {"id": request_id})
                    finalized = False  # allow further events (e.g. trailing)

            # Drain remaining buffered objects.
            if request_id:
                for obj in parser.drain():
                    await analyze_stream_data(obj, request_id)
        except asyncio.CancelledError:
            # Client disconnected - cancel upstream and mark request cancelled.
            await upstream.aclose()
            if request_id:
                await request_tracker.cancel_request(request_id, "Client disconnected")
                await websocket_manager.send_event("request_cancelled", {"id": request_id})
            raise
        except Exception as e:
            if request_id:
                await request_tracker.error_request(request_id, str(e))
                await websocket_manager.send_event("request_failed", {"id": request_id, "error": str(e)})
            raise
        finally:
            # Ensure the request is finalized if never done (e.g. non-stream JSON).
            if request_id and request_id in request_tracker.running_requests:
                await request_tracker.complete_request(request_id, "COMPLETED")
                await websocket_manager.send_event("request_completed", {"id": request_id})
            await upstream.aclose()

    if is_stream:
        return StreamingResponse(
            stream_generator(),
            media_type=content_type or "application/x-ndjson",
            headers=resp_headers,
            status_code=upstream.status_code,
        )

    # Non-streaming JSON - buffer the (small) body, persist, return.
    response_body = b""
    try:
        async for chunk in upstream.aiter_bytes():
            response_body += chunk
    except Exception as e:
        if request_id:
            await request_tracker.error_request(request_id, str(e))
        return Response(content=json.dumps({"error": str(e)}), status_code=502)

    if request_id:
        # Non-streaming chat/generate still carry final metrics.
        try:
            obj = json.loads(response_body)
            await analyze_stream_data(obj, request_id)
            await request_tracker.complete_request(request_id, "COMPLETED")
            await websocket_manager.send_event("request_completed", {"id": request_id})
        except (json.JSONDecodeError, ValueError):
            await request_tracker.complete_request(request_id, "COMPLETED")
            await websocket_manager.send_event("request_completed", {"id": request_id})

    return Response(
        content=response_body,
        media_type=content_type or "application/json",
        status_code=upstream.status_code,
        headers=resp_headers,
    )
