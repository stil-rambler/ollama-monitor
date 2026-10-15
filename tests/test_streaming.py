"""
Tests for StreamParser and analyze_stream_data.
"""

from __future__ import annotations

import json

import pytest

from app.proxy.streaming import StreamParser, analyze_stream_data


def test_parser_single_object():
    parser = StreamParser()
    parser.update('{"a": 1}')
    objs = parser.drain()
    assert len(objs) == 1
    assert objs[0] == {"a": 1}


def test_parser_split_chunks():
    """JSON object split across multiple network chunks."""
    parser = StreamParser()
    full = '{"model":"m","response":"hello","done":false}\n'
    # Feed one char at a time to simulate fragmented chunks.
    for ch in full:
        parser.update(ch)
    objs = parser.drain()
    assert len(objs) == 1
    assert objs[0]["response"] == "hello"


def test_parser_multiple_ndjson_lines():
    parser = StreamParser()
    stream = (
        '{"response":"a","done":false}\n'
        '{"response":"b","done":false}\n'
        '{"response":"c","done":true,"eval_count":3,"eval_duration":1000000000}\n'
    )
    parser.update(stream)
    objs = parser.drain()
    assert len(objs) == 3
    assert objs[-1]["done"] is True


def test_parser_ssesque_prefix():
    """Tolerates data: prefixes in SSE-like streams."""
    parser = StreamParser()
    parser.update('data: {"a":1}\n\ndata: {"b":2}\n\n')
    objs = parser.drain()
    assert len(objs) == 2


def test_parser_garbage_ignored():
    parser = StreamParser()
    parser.update("garbage\n{not json}\n")
    assert parser.drain() == []


@pytest.mark.asyncio
async def test_analyze_stream_extracts_stats(db_session_factory):
    from app.services.request_tracker import request_tracker
    rid = await request_tracker.start_request(
        client_ip="127.0.0.1",
        client_port=1,
        client_name="Test",
        method="POST",
        endpoint="/api/chat",
        query_params={},
        request_body={"model": "m"},
        request_headers={},
        monitoring_mode="proxy",
    )
    obj = {
        "model": "m",
        "response": "hi",
        "done": True,
        "eval_count": 5,
        "prompt_eval_count": 10,
        "eval_duration": 1000000000,
        "prompt_eval_duration": 500000000,
        "load_duration": 100000000,
    }
    analysis = await analyze_stream_data(obj, rid)
    assert analysis.get("done") is True
    req = request_tracker.running_requests[rid]
    assert req.eval_count == 5
    assert req.prompt_eval_count == 10
    assert req.generation_speed is not None and req.generation_speed > 0
    await request_tracker.complete_request(rid, "COMPLETED")
