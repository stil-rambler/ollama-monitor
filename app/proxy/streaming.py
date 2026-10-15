"""
Streaming response handling for the Ollama Monitor proxy.

The parser splits raw byte chunks into JSON objects even when object boundaries
do not align with network chunk boundaries, and extracts timing/token statistics
from Ollama completion events and from OpenAI-compatible `usage` payloads.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, List, Optional

from app.services.request_tracker import request_tracker

logger = logging.getLogger(__name__)


class StreamParser:
    """Split a byte/text stream into JSON objects (NDJSON / SSE tolerant)."""

    def __init__(self) -> None:
        self.buffer = ""
        self.parsed_objects: List[dict] = []
        self.is_complete = False
        self.last_event_time: Optional[float] = None

    def update(self, chunk: str) -> None:
        """Feed a text chunk into the parser, extracting complete JSON objects."""
        if not chunk:
            return
        self.buffer += chunk
        while True:
            start = self.buffer.find("{")
            if start == -1:
                self.buffer = ""
                break
            # Find the matching closing brace, respecting strings and escapes.
            depth = 0
            end = start
            in_string = False
            escaped = False
            while end < len(self.buffer):
                ch = self.buffer[end]
                if in_string:
                    if escaped:
                        escaped = False
                    elif ch == "\\":
                        escaped = True
                    elif ch == '"':
                        in_string = False
                else:
                    if ch == '"':
                        in_string = True
                    elif ch == "{":
                        depth += 1
                    elif ch == "}":
                        depth -= 1
                        if depth == 0:
                            end += 1
                            break
                end += 1
            if depth != 0:
                # Incomplete object - keep remainder in buffer and wait.
                break
            json_str = self.buffer[start:end]
            self.buffer = self.buffer[end:]
            try:
                obj = json.loads(json_str)
                self.parsed_objects.append(obj)
                self.last_event_time = time.time()
            except json.JSONDecodeError:
                # Skip malformed fragment; do not accumulate it.
                self.buffer = self.buffer.lstrip()
                continue

    def get_parsed_objects(self) -> List[dict]:
        return self.parsed_objects

    def get_last_event_time(self) -> Optional[float]:
        return self.last_event_time

    def drain(self) -> List[dict]:
        objs = self.parsed_objects
        self.parsed_objects = []
        return objs


async def analyze_stream_data(json_obj: Dict[str, Any], request_id: str) -> Dict[str, Any]:
    """
    Extract statistics from a single streamed JSON object and update the
    tracked request. Returns the analysis dict (with a 'done' flag when the
    final completion event was seen).
    """
    analysis: Dict[str, Any] = {}
    is_done = bool(json_obj.get("done"))

    if "model" in json_obj:
        analysis["model_name"] = json_obj["model"]

    # Ollama native completion event.
    if "eval_count" in json_obj:
        analysis["eval_count"] = json_obj["eval_count"]
    if "prompt_eval_count" in json_obj:
        analysis["prompt_eval_count"] = json_obj["prompt_eval_count"]
    if "eval_duration" in json_obj:
        analysis["eval_duration"] = json_obj["eval_duration"]
    if "prompt_eval_duration" in json_obj:
        analysis["prompt_eval_duration"] = json_obj["prompt_eval_duration"]
    if "load_duration" in json_obj:
        analysis["model_load_duration"] = json_obj["load_duration"]
    # NOTE: Ollama total_duration is in nanoseconds; the proxy measures its own
    # wall-clock total_duration in milliseconds, so we do not overwrite it here.

    # Native token stream.
    if "response" in json_obj:
        analysis["parsed_object"] = json_obj

    # OpenAI-compatible usage.
    usage = json_obj.get("usage") or {}
    if isinstance(usage, dict):
        if "prompt_tokens" in usage:
            analysis["prompt_eval_count"] = usage["prompt_tokens"]
        if "completion_tokens" in usage:
            analysis["eval_count"] = usage["completion_tokens"]
        if "total_tokens" in usage:
            analysis["total_tokens"] = usage["total_tokens"]

    # OpenAI chat completion chunk may carry usage in the final chunk.
    if isinstance(json_obj.get("choices"), list) and is_done:
        choice = json_obj["choices"][0] if json_obj["choices"] else {}
        if isinstance(choice, dict) and "text" in choice and choice["text"]:
            analysis["parsed_object"] = {"response": choice["text"], "done": True}

    if is_done:
        analysis["done"] = True

    if analysis and request_id:
        await request_tracker.update_request(request_id, analysis)
    return analysis


async def parse_stream_response(stream_response: str, request_id: str) -> Dict[str, Any]:
    """
    Parse a full stream response string and extract statistics.
    (Used mainly by tests / non-streaming fallback.)
    """
    parser = StreamParser()
    parser.update(stream_response)
    stats: Dict[str, Any] = {
        "request_id": request_id,
        "parsed_objects": parser.get_parsed_objects(),
        "last_event_time": parser.get_last_event_time(),
    }
    await request_tracker.update_request(request_id, stats)
    return stats
