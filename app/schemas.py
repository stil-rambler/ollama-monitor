"""
Pydantic schemas for Ollama Monitor API validation.
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field, ConfigDict


class Request(BaseModel):
    """Schema for Request model - API validation."""

    model_config = ConfigDict(from_attributes=True)

    id: str = Field(..., description="Request ID")
    created_at: Optional[datetime] = Field(None, description="Request creation timestamp")
    started_at: Optional[datetime] = Field(None, description="Request start timestamp")
    finished_at: Optional[datetime] = Field(None, description="Request finish timestamp")
    client_ip: Optional[str] = Field(None, description="Client IP address")
    client_port: Optional[int] = Field(None, description="Client port")
    method: str = Field(..., description="HTTP method")
    endpoint: str = Field(..., description="API endpoint")
    model_name: Optional[str] = Field(None, description="Model name")
    operation_type: str = Field(..., description="Operation type (chat, generate, embedding, model_load, model_pull, model_create, other)")
    http_status: int = Field(..., description="HTTP status code")
    execution_status: str = Field(..., description="Execution status (COMPLETED, ERROR, CANCELLED, INTERRUPTED)")
    request_size: Optional[int] = Field(None, description="Request size in bytes")
    response_size: Optional[int] = Field(None, description="Response size in bytes")
    user_agent: Optional[str] = Field(None, description="User-Agent header")
    client_name: Optional[str] = Field(None, description="Client name (OpenCode, VSCode, PythonScript, etc.)")
    monitoring_mode: str = Field(..., description="Monitoring mode (passive, proxy)")
    data_source: str = Field(..., description="Data source (Ollama, Monitor, API, Proxy)")
    session_id: Optional[str] = Field(None, description="Optional session grouping id")
    error_message: Optional[str] = Field(None, description="Error message if any")

    # Timing metrics
    total_duration: Optional[int] = Field(None, description="Total duration in milliseconds")
    model_load_duration: Optional[int] = Field(None, description="Model load duration in nanoseconds")
    prompt_eval_duration: Optional[int] = Field(None, description="Prompt evaluation duration in nanoseconds")
    eval_duration: Optional[int] = Field(None, description="Evaluation duration in nanoseconds")
    first_byte_time: Optional[int] = Field(None, description="Time until first byte in milliseconds")
    first_token_time: Optional[int] = Field(None, description="Time until first token in milliseconds")
    response_transfer_time: Optional[int] = Field(None, description="Response transfer time in milliseconds")

    # Token metrics
    prompt_eval_count: Optional[int] = Field(None, description="Number of prompt tokens evaluated")
    eval_count: Optional[int] = Field(None, description="Number of output tokens generated")
    total_tokens: Optional[int] = Field(None, description="Total number of tokens processed")
    output_tokens: Optional[int] = Field(None, description="Number of output tokens generated")
    generation_speed: Optional[float] = Field(None, description="Generation speed in tokens per second")
    prompt_processing_speed: Optional[float] = Field(None, description="Prompt processing speed in tokens per second")


class Model(BaseModel):
    """Schema for Model model - API validation."""

    model_config = ConfigDict(from_attributes=True)

    id: str = Field(..., description="Model ID")
    name: str = Field(..., description="Model name")
    size: Optional[int] = Field(None, description="Model size in bytes")
    gpu_memory_size: Optional[int] = Field(None, description="GPU memory size in bytes")
    context_length: Optional[int] = Field(None, description="Context length")
    quantization_type: Optional[str] = Field(None, description="Quantization type")
    last_loaded: Optional[datetime] = Field(None, description="Last load timestamp")
    last_unloaded: Optional[datetime] = Field(None, description="Last unload timestamp")
    total_requests: int = Field(0, description="Total number of requests")
    average_generation_speed: Optional[float] = Field(None, description="Average generation speed in tokens per second")
    average_prompt_processing_speed: Optional[float] = Field(None, description="Average prompt processing speed in tokens per second")
    average_response_time: Optional[int] = Field(None, description="Average response time in milliseconds")
    total_input_tokens: int = Field(0, description="Total number of input tokens")
    total_output_tokens: int = Field(0, description="Total number of output tokens")
    total_errors: int = Field(0, description="Total number of errors")


class Client(BaseModel):
    """Schema for Client model - API validation."""

    model_config = ConfigDict(from_attributes=True)

    id: str = Field(..., description="Client ID")
    client_ip: str = Field(..., description="Client IP address")
    client_name: Optional[str] = Field(None, description="Client name")
    user_agent: Optional[str] = Field(None, description="User-Agent header")
    total_requests: int = Field(0, description="Total number of requests")
    last_active: Optional[datetime] = Field(None, description="Last active timestamp")
    total_request_duration: int = Field(0, description="Total request duration in milliseconds")
    average_response_time: Optional[int] = Field(None, description="Average response time in milliseconds")
    used_models: List[str] = Field(default_factory=list, description="List of model names used")


class GpuMetric(BaseModel):
    """Schema for GpuMetric model - API validation."""

    model_config = ConfigDict(from_attributes=True)

    id: str = Field(..., description="GPU metric ID")
    created_at: Optional[datetime] = Field(None, description="Metric creation timestamp")
    gpu_index: int = Field(..., description="GPU index")
    gpu_name: str = Field(..., description="GPU name")
    gpu_uuid: str = Field(..., description="GPU UUID")
    total_vram: int = Field(..., description="Total VRAM in bytes")
    used_vram: int = Field(..., description="Used VRAM in bytes")
    free_vram: int = Field(..., description="Free VRAM in bytes")
    gpu_load: int = Field(..., description="GPU load percentage (0-100)")
    memory_load: Optional[int] = Field(None, description="Memory load percentage (0-100)")
    temperature: Optional[int] = Field(None, description="Temperature in degrees Celsius")
    power_usage: Optional[int] = Field(None, description="Power usage in watts")
    power_limit: Optional[int] = Field(None, description="Power limit in watts")
    gpu_frequency: Optional[int] = Field(None, description="GPU frequency in MHz")
    memory_frequency: Optional[int] = Field(None, description="Memory frequency in MHz")


class SystemEvent(BaseModel):
    """Schema for SystemEvent model - API validation."""

    model_config = ConfigDict(from_attributes=True)

    id: str = Field(..., description="Event ID")
    created_at: Optional[datetime] = Field(None, description="Event creation timestamp")
    event_type: str = Field(..., description="Event type (status, error, warning, info)")
    message: str = Field(..., description="Event message")
    source: str = Field(..., description="Event source (OllamaMonitor, Ollama, Proxy, GPU, System)")
    details: Optional[dict] = Field(None, description="Additional event details")


class Setting(BaseModel):
    """Schema for Setting model - API validation."""

    model_config = ConfigDict(from_attributes=True)

    id: str = Field(..., description="Setting ID")
    key: str = Field(..., description="Setting key")
    value: str = Field(..., description="Setting value")
    data_type: str = Field(..., description="Data type (string, int, float, boolean, json)")
