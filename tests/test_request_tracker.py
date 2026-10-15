"""
Tests for RequestTracker lifecycle and persistence.
"""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_request_lifecycle_completed(db_session_factory):
    from app.services.request_tracker import request_tracker
    from app.database import Request
    from sqlalchemy import select

    rid = await request_tracker.start_request(
        client_ip="10.0.0.5",
        client_port=1234,
        client_name="OpenCode",
        method="POST",
        endpoint="/api/chat",
        query_params={},
        request_body={"model": "gpt-test"},
        request_headers={"User-Agent": "OpenCode/1.0"},
        monitoring_mode="proxy",
    )
    assert rid in request_tracker.running_requests

    await request_tracker.update_request(rid, {"parsed_object": {"response": "hello", "done": True}})
    await request_tracker.complete_request(rid, "COMPLETED")

    assert rid not in request_tracker.running_requests
    assert rid in request_tracker.completed_requests
    req = request_tracker.completed_requests[rid]
    assert req.execution_status == "COMPLETED"
    assert req.client_name == "OpenCode"
    assert req.model_name == "gpt-test"


@pytest.mark.asyncio
async def test_request_error_status(db_session_factory):
    from app.services.request_tracker import request_tracker

    rid = await request_tracker.start_request(
        client_ip="10.0.0.6", client_port=1, client_name="Test", method="POST",
        endpoint="/api/chat", query_params={}, request_body=None,
        request_headers={}, monitoring_mode="proxy",
    )
    await request_tracker.error_request(rid, "boom", http_status=500)
    req = request_tracker.completed_requests[rid]
    assert req.execution_status == "ERROR"
    assert req.http_status == 500
    assert req.error_message == "boom"


@pytest.mark.asyncio
async def test_operation_type_detection(db_session_factory):
    from app.services.request_tracker import request_tracker
    rid = await request_tracker.start_request(
        client_ip="1.1.1.1", client_port=1, client_name="T", method="POST",
        endpoint="/api/embed", query_params={}, request_body={},
        request_headers={}, monitoring_mode="proxy",
    )
    req = request_tracker.running_requests[rid]
    assert req.operation_type == "embedding"
    await request_tracker.cancel_request(rid)
