"""
Tests for configuration loading and validation.
"""

from __future__ import annotations

import pytest

from app.config import Config, load_config_from_yaml


def test_default_config_values():
    cfg = Config()
    assert cfg.server_port == 8881
    assert cfg.server_host == "127.0.0.1"
    assert cfg.ollama_base_url == "http://127.0.0.1:11434"
    assert cfg.monitoring_gpu_interval >= 1


def test_port_validation():
    with pytest.raises(Exception):
        Config(server_port=99999)
    with pytest.raises(Exception):
        Config(server_port=0)


def test_base_url_validation():
    with pytest.raises(Exception):
        Config(ollama_base_url="ollama:11434")


def test_config_yaml_loads():
    cfg = load_config_from_yaml()
    assert cfg.server_port in (8881, 18881)
    assert cfg.ollama_base_url.startswith("http")


def test_database_url():
    cfg = Config(database_path="data/x.db")
    url = cfg.get_database_url()
    assert url.startswith("sqlite+aiosqlite:///")
    assert "x.db" in url
