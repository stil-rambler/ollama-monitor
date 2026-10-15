"""
Request tracking system for Ollama Monitor.

Tracks the lifecycle of proxied requests: creation, live updates while the
stream is flowing, and final persistence (COMPLETED / ERROR / CANCELLED).
A module-level singleton is shared by the proxy pipeline.

Database writes are best-effort and never block the streaming path: failures
are logged and swallowed so a DB hiccup cannot break proxy responses.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta
from typing import Any, Dict, Optional
from uuid import uuid4

from sqlalchemy import select

from app.database import (
    Client,
    Model,
    Request,
    get_session,
)

logger = logging.getLogger(__name__)

# Fixed default for the "application did not signal completion" timeout (ms).
DEFAULT_TIMEOUT_MS = 600_000


class RequestTracker:
    """Tracks requests in memory and persists them to SQLite."""

    def __init__(self) -> None:
        self.running_requests: Dict[str, Request] = {}
        self.started: Dict[str, float] = {}
        self.first_token_at: Dict[str, float] = {}
        self.first_byte_at: Dict[str, float] = {}
        self.completed_requests: Dict[str, Request] = {}
        self.request_locks: Dict[str, Any] = {}

    # ------------------------------------------------------------------ #
    # Lifecycle
    # ------------------------------------------------------------------ #
    async def start_request(
        self,
        client_ip: str,
        client_port: int,
        client_name: str,
        method: str,
        endpoint: str,
        query_params: Dict[str, str],
        request_body: Optional[Dict[str, Any]],
        request_headers: Dict[str, str],
        monitoring_mode: str,
        session_id: Optional[str] = None,
    ) -> str:
        """Create and register a new request, returning its id."""
        request_id = str(uuid4())
        now = datetime.utcnow()
        body_size = self._get_body_size(request_body)

        operation_type = self._determine_operation_type(endpoint)
        model_name = None
        if isinstance(request_body, dict):
            model_name = request_body.get("model")

        request = Request(
            id=request_id,
            created_at=now,
            started_at=now,
            finished_at=None,
            client_ip=client_ip,
            client_port=client_port,
            method=method,
            endpoint=endpoint,
            model_name=model_name,
            operation_type=operation_type,
            http_status=200,
            execution_status="RUNNING",
            request_size=body_size,
            response_size=None,
            user_agent=(request_headers or {}).get("User-Agent", ""),
            client_name=client_name,
            monitoring_mode=monitoring_mode,
            data_source="Proxy",
            session_id=session_id,
            error_message=None,
            total_duration=None,
            model_load_duration=None,
            prompt_eval_duration=None,
            eval_duration=None,
            first_byte_time=None,
            first_token_time=None,
            response_transfer_time=None,
            prompt_eval_count=None,
            eval_count=None,
            total_tokens=None,
            output_tokens=None,
            generation_speed=None,
            prompt_processing_speed=None,
        )

        self.running_requests[request_id] = request
        self.started[request_id] = time.monotonic()
        self.request_locks[request_id] = __import__("asyncio").Lock()
        logger.info("Started request %s (%s %s) from %s", request_id, method, endpoint, client_ip)
        return request_id

    async def update_request(self, request_id: str, data: Dict[str, Any]) -> None:
        """Apply streaming/analysis updates to a running request."""
        request = self.running_requests.get(request_id)
        if request is None:
            return

        lock = self.request_locks.get(request_id)
        if lock:
            async with lock:
                self._apply_updates(request, data)

    def _apply_updates(self, request: Request, data: Dict[str, Any]) -> None:
        """Apply a dict of updates onto a Request object."""
        for key, value in data.items():
            if value is None:
                continue
            if key == "parsed_object" and isinstance(value, dict):
                obj = value
                if obj.get("done"):
                    if obj.get("eval_count") is not None:
                        request.eval_count = obj["eval_count"]
                    if obj.get("prompt_eval_count") is not None:
                        request.prompt_eval_count = obj["prompt_eval_count"]
                    if obj.get("eval_duration") is not None:
                        request.eval_duration = obj["eval_duration"]
                    if obj.get("prompt_eval_duration") is not None:
                        request.prompt_eval_duration = obj["prompt_eval_duration"]
                    if obj.get("load_duration") is not None:
                        request.model_load_duration = obj["load_duration"]
                    # NOTE: Ollama total_duration is in nanoseconds while our
                    # total_duration column is proxy wall-clock ms - do not mix.
                    if obj.get("response"):
                        request.output_tokens = len(obj["response"])
                    if request.eval_count is not None and request.output_tokens is None:
                        request.output_tokens = request.eval_count
                elif obj.get("response"):
                    if self.first_token_at.get(request.id) is None:
                        self.first_token_at[request.id] = time.monotonic()
                    if request.output_tokens is None:
                        request.output_tokens = 0
                    request.output_tokens += len(obj["response"])
                # Update model name if it arrives in the stream.
                if obj.get("model") and not request.model_name:
                    request.model_name = obj["model"]
                continue

            if hasattr(request, key):
                setattr(request, key, value)

        # Recompute derived values.
        started = self.started.get(request.id)
        if started is not None and request.total_duration is None:
            elapsed_ms = (time.monotonic() - started) * 1000
            request.total_duration = int(elapsed_ms)

        if request.eval_count and request.eval_duration:
            try:
                request.generation_speed = request.eval_count / (request.eval_duration / 1_000_000_000)
            except ZeroDivisionError:
                request.generation_speed = None
        if request.prompt_eval_count and request.prompt_eval_duration:
            try:
                request.prompt_processing_speed = (
                    request.prompt_eval_count / (request.prompt_eval_duration / 1_000_000_000)
                )
            except ZeroDivisionError:
                request.prompt_processing_speed = None

        if request.prompt_eval_count is not None and request.eval_count is not None:
            request.total_tokens = request.prompt_eval_count + request.eval_count

    async def mark_first_byte(self, request_id: str) -> None:
        if request_id in self.running_requests and request_id not in self.first_byte_at:
            self.first_byte_at[request_id] = time.monotonic()

    async def complete_request(
        self,
        request_id: str,
        status: str = "COMPLETED",
        error: Optional[str] = None,
        http_status: Optional[int] = None,
    ) -> None:
        """Finalize a request and persist it."""
        request = self.running_requests.get(request_id)
        if request is None:
            return

        request.finished_at = datetime.utcnow()
        request.execution_status = status
        if error:
            request.error_message = error
        if http_status is not None:
            request.http_status = http_status

        started = self.started.get(request_id)
        if started is not None:
            elapsed_ms = (time.monotonic() - started) * 1000
            # Keep the more precise wall-clock duration unless Ollama already set one.
            if request.total_duration is None:
                request.total_duration = int(elapsed_ms)
            first_byte = self.first_byte_at.get(request_id)
            if first_byte is not None:
                request.first_byte_time = int((first_byte - started) * 1000)
            first_token = self.first_token_at.get(request_id)
            if first_token is not None:
                request.first_token_time = int((first_token - started) * 1000)
            request.response_transfer_time = int(elapsed_ms)  # proxy-side transfer time

        if request.total_duration is None:
            request.total_duration = 0

        await self._persist(request)

        self.completed_requests[request_id] = request
        self.running_requests.pop(request_id, None)
        self.request_locks.pop(request_id, None)
        self.started.pop(request_id, None)
        self.first_token_at.pop(request_id, None)
        self.first_byte_at.pop(request_id, None)
        logger.info("Completed request %s with status %s", request_id, status)

    async def cancel_request(self, request_id: str, error: Optional[str] = None) -> None:
        await self.complete_request(request_id, status="CANCELLED", error=error)

    async def error_request(self, request_id: str, error: str, http_status: Optional[int] = None) -> None:
        await self.complete_request(request_id, status="ERROR", error=error, http_status=http_status)

    # ------------------------------------------------------------------ #
    # Persistence
    # ------------------------------------------------------------------ #
    async def _persist(self, request: Request) -> None:
        """Save request + associated model/client rows. Best effort."""
        try:
            async with await get_session() as session:
                if request.model_name:
                    result = await session.execute(
                        select(Model).where(Model.name == request.model_name)
                    )
                    model = result.scalar_one_or_none()
                    if model is None:
                        model = Model(name=request.model_name)
                        session.add(model)
                    model.total_requests = (model.total_requests or 0) + 1
                    model.total_input_tokens = (model.total_input_tokens or 0) + (
                        request.prompt_eval_count or 0
                    )
                    model.total_output_tokens = (model.total_output_tokens or 0) + (
                        request.eval_count or 0
                    )
                    if request.execution_status == "ERROR":
                        model.total_errors = (model.total_errors or 0) + 1
                    if request.generation_speed is not None:
                        prev = model.average_generation_speed
                        model.average_generation_speed = (
                            (prev or 0) + request.generation_speed
                        ) / 2
                    if request.prompt_processing_speed is not None:
                        prev = model.average_prompt_processing_speed
                        model.average_prompt_processing_speed = (
                            (prev or 0) + request.prompt_processing_speed
                        ) / 2
                    if request.total_duration is not None:
                        model.average_response_time = request.total_duration
                    model.last_loaded = request.finished_at

                if request.client_ip:
                    result = await session.execute(
                        select(Client).where(Client.client_ip == request.client_ip)
                    )
                    client = result.scalar_one_or_none()
                    if client is None:
                        client = Client(
                            client_ip=request.client_ip,
                            client_name=request.client_name,
                            user_agent=request.user_agent,
                        )
                        session.add(client)
                    client.total_requests = (client.total_requests or 0) + 1
                    client.last_active = datetime.utcnow()
                    client.total_request_duration = (client.total_request_duration or 0) + (
                        request.total_duration or 0
                    )
                    if request.total_duration is not None:
                        client.average_response_time = request.total_duration
                    if request.model_name:
                        used = list(client.used_models or [])
                        if request.model_name not in used:
                            used.append(request.model_name)
                            client.used_models = used

                session.add(request)
                await session.commit()
        except Exception as e:
            logger.error("Error persisting request %s: %s", request.id, e)

    async def mark_interrupted_on_startup(self) -> None:
        """Mark any RUNNING rows from a previous run as INTERRUPTED."""
        try:
            async with await get_session() as session:
                result = await session.execute(
                    select(Request).where(Request.execution_status == "RUNNING")
                )
                rows = result.scalars().all()
                for row in rows:
                    row.execution_status = "INTERRUPTED"
                    if row.finished_at is None:
                        row.finished_at = datetime.utcnow()
                await session.commit()
                if rows:
                    logger.info("Marked %d stale RUNNING request(s) as INTERRUPTED", len(rows))
        except Exception as e:
            logger.error("Error marking interrupted requests: %s", e)

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #
    def get_running(self) -> list[dict]:
        return [r.to_dict() for r in self.running_requests.values()]

    def _determine_operation_type(self, endpoint: str) -> str:
        if endpoint in ("/api/chat", "/api/generate"):
            return "chat"
        if endpoint in ("/api/embed", "/api/embeddings", "/v1/embeddings"):
            return "embedding"
        if endpoint in ("/v1/chat/completions", "/v1/completions"):
            return "chat"
        if endpoint == "/api/pull":
            return "model_pull"
        if endpoint == "/api/create":
            return "model_create"
        if endpoint == "/api/delete":
            return "model_delete"
        if endpoint == "/api/copy":
            return "model_copy"
        if endpoint == "/api/show":
            return "model_show"
        return "other"

    def _get_body_size(self, body: Optional[Dict[str, Any]]) -> Optional[int]:
        if body is None:
            return None
        try:
            return len(__import__("json").dumps(body).encode("utf-8"))
        except Exception:
            return None


# Module-level singleton shared by the proxy pipeline.
request_tracker = RequestTracker()
