from __future__ import annotations

import pytest

from cfebms.config import Settings


def test_settings_load_runtime_values_from_environment(monkeypatch) -> None:
    monkeypatch.setenv("CFE_BATTERY_HOST", "battery.example")
    monkeypatch.setenv("CFE_BATTERY_PORT", "6868")
    monkeypatch.setenv("MQTT_DISCOVERY_PREFIX", "homeassistant")
    settings = Settings.from_env()
    assert settings.battery_host == "battery.example"
    assert settings.battery_port == 6868
    assert settings.discovery_prefix == "homeassistant"
    assert settings.telemetry_stale_after == 300.0


def test_settings_require_battery_host(monkeypatch) -> None:
    monkeypatch.delenv("CFE_BATTERY_HOST", raising=False)
    with pytest.raises(ValueError, match="CFE_BATTERY_HOST is required"):
        Settings.from_env()


def test_heartbeat_log_interval_defaults_to_60_and_can_be_disabled(monkeypatch) -> None:
    monkeypatch.setenv("CFE_BATTERY_HOST", "battery.example")
    monkeypatch.delenv("HEARTBEAT_LOG_INTERVAL_MIN", raising=False)
    assert Settings.from_env().heartbeat_log_interval_min == 60
    monkeypatch.setenv("HEARTBEAT_LOG_INTERVAL_MIN", "0")
    assert Settings.from_env().heartbeat_log_interval_min == 0


def test_heartbeat_log_interval_rejects_negative_values(monkeypatch) -> None:
    monkeypatch.setenv("CFE_BATTERY_HOST", "battery.example")
    monkeypatch.setenv("HEARTBEAT_LOG_INTERVAL_MIN", "-1")
    with pytest.raises(ValueError, match="HEARTBEAT_LOG_INTERVAL_MIN must be zero or positive"):
        Settings.from_env()
