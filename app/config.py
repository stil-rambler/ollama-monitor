"""
Configuration module for Ollama Monitor.

Loads values from `config.yaml` (or a path given via OLLAMA_MONITOR_CONFIG),
then applies environment variables prefixed with OLLAMA_MONITOR_.
"""

from __future__ import annotations

import logging
import socket
from pathlib import Path
from typing import Optional

import yaml
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Config(BaseSettings):
    """Application configuration with validation."""

    model_config = SettingsConfigDict(
        env_prefix="OLLAMA_MONITOR_",
        case_sensitive=False,
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Server settings
    server_host: str = Field("127.0.0.1", description="Host to bind the server to")
    server_port: int = Field(8881, description="Port to bind the server to")

    # Ollama settings
    ollama_base_url: str = Field(
        "http://127.0.0.1:11434", description="Base URL of the Ollama server"
    )
    ollama_timeout: int = Field(600, description="Timeout for Ollama requests in seconds")

    # Monitoring settings
    monitoring_passive_enabled: bool = Field(True, description="Enable passive monitoring mode")
    monitoring_proxy_enabled: bool = Field(True, description="Enable proxy monitoring mode")
    monitoring_gpu_interval: int = Field(1, description="Interval for GPU monitoring in seconds")
    monitoring_ollama_interval: int = Field(5, description="Interval for Ollama status monitoring in seconds")

    # Database settings
    database_path: str = Field("data/ollama_monitor.db", description="Path to the SQLite database file")

    # Retention settings
    retention_requests_days: int = Field(90, description="Days to retain request history")
    retention_gpu_raw_hours: int = Field(24, description="Hours to retain raw GPU metrics")
    retention_gpu_aggregated_days: int = Field(30, description="Days to retain aggregated GPU metrics")

    # Logging settings
    logging_level: str = Field("INFO", description="Logging level (DEBUG, INFO, WARNING, ERROR)")
    logging_save_request_body: bool = Field(False, description="Save request body in logs")
    logging_save_response_body: bool = Field(False, description="Save response body in logs")

    # Security
    auth_token: Optional[str] = Field(
        None, description="Optional auth token required for API/UI access when listening on 0.0.0.0"
    )

    # UI settings
    ui_language: str = Field("ru", description="Default language for the UI")
    ui_theme: str = Field("dark", description="Default theme for the UI (dark/light)")

    @field_validator("server_port")
    @classmethod
    def _validate_port(cls, v: int) -> int:
        if not 1 <= v <= 65535:
            raise ValueError("Port must be between 1 and 65535")
        return v

    @field_validator("monitoring_gpu_interval", "monitoring_ollama_interval")
    @classmethod
    def _validate_interval(cls, v: int) -> int:
        if v < 1:
            raise ValueError("Monitoring intervals must be at least 1 second")
        return v

    @field_validator("retention_requests_days", "retention_gpu_raw_hours", "retention_gpu_aggregated_days")
    @classmethod
    def _validate_retention(cls, v: int) -> int:
        if v < 1:
            raise ValueError("Retention must be at least 1")
        return v

    @field_validator("ollama_base_url")
    @classmethod
    def _validate_base_url(cls, v: str) -> str:
        v = v.rstrip("/")
        if not (v.startswith("http://") or v.startswith("https://")):
            raise ValueError("ollama_base_url must start with http:// or https://")
        return v

    def ensure_paths(self) -> None:
        """Ensure all required directories exist."""
        data_dir = Path(self.database_path).parent
        data_dir.mkdir(parents=True, exist_ok=True)
        logs_dir = PROJECT_ROOT / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)

    def validate_port_availability(self) -> bool:
        """Return False if the configured port is already in use."""
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.settimeout(1.0)
                return sock.connect_ex((self.server_host, self.server_port)) != 0
        except Exception as e:  # pragma: no cover
            logger.warning(f"Could not check port availability: {e}")
            return True

    def get_database_url(self) -> str:
        """Get the SQLite URL for SQLAlchemy."""
        db_path = Path(self.database_path)
        if not db_path.is_absolute():
            db_path = PROJECT_ROOT / db_path
        return f"sqlite+aiosqlite:///{db_path.as_posix()}"


def load_config_from_yaml(path: Optional[str] = None) -> "Config":
    """Build a Config instance, overlaying values from a YAML file if present."""
    config_path = Path(path) if path else Path(
        __import__("os").environ.get("OLLAMA_MONITOR_CONFIG", "config.yaml")
    )
    if not config_path.is_absolute():
        config_path = PROJECT_ROOT / config_path

    values: dict = {}
    if config_path.exists():
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                raw = yaml.safe_load(f) or {}
            # Flatten nested structure (server.host -> server_host)
            mapping = {
                "server": ["host", "port"],
                "ollama": ["base_url", "timeout"],
                "monitoring": [
                    "passive_enabled",
                    "proxy_enabled",
                    "gpu_interval",
                    "ollama_interval",
                ],
                "database": ["path"],
                "retention": [
                    "requests_days",
                    "gpu_raw_hours",
                    "gpu_aggregated_days",
                ],
                "logging": ["level", "save_request_body", "save_response_body"],
                "ui": ["language", "theme"],
                "security": ["auth_token"],
            }
            for section, keys in mapping.items():
                section_data = raw.get(section, {})
                if not isinstance(section_data, dict):
                    continue
                for key in keys:
                    if key in section_data:
                        values[f"{section}_{key}"] = section_data[key]
            logger.info(f"Loaded configuration from {config_path}")
        except Exception as e:
            logger.warning(f"Failed to parse {config_path}: {e}")
    else:
        logger.info("config.yaml not found, using defaults / environment variables")

    return Config(**values)
