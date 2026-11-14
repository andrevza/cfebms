"""Environment-based runtime configuration."""

from __future__ import annotations

import os
import math
from dataclasses import dataclass


def _int_env(name: str, default: int, *, allowed: set[int] | None = None) -> int:
    raw = os.getenv(name)
    try:
        value = default if raw in (None, "") else int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if allowed is not None and value not in allowed:
        raise ValueError(f"{name} must be one of {sorted(allowed)}")
    return value


def _float_env(name: str, default: float) -> float:
    raw = os.getenv(name)
    try:
        value = default if raw in (None, "") else float(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be numeric") from exc
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be positive")
    return value


@dataclass(frozen=True, slots=True)
class Settings:
    battery_host: str
    battery_port: int = 6868
    connect_timeout: float = 5.0
    read_timeout: float = 10.0
    reconnect_delay: float = 5.0
    stale_after: float = 30.0
    telemetry_stale_after: float = 300.0
    mqtt_host: str = "mqtt.example.com"
    mqtt_port: int = 1883
    mqtt_username: str | None = None
    mqtt_password: str | None = None
    discovery_prefix: str = "homeassistant"
    base_topic: str = "cfebms"
    log_level: str = "INFO"
    heartbeat_log_interval_min: int = 60

    @classmethod
    def from_env(cls) -> "Settings":
        battery_host = os.getenv("CFE_BATTERY_HOST", "").strip()
        if not battery_host:
            raise ValueError("CFE_BATTERY_HOST is required")
        log_level = os.getenv("LOG_LEVEL", "INFO").strip().upper()
        if log_level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ValueError("LOG_LEVEL must be DEBUG, INFO, WARNING, ERROR, or CRITICAL")
        username = os.getenv("MQTT_USERNAME", "").strip() or None
        password = os.getenv("MQTT_PASSWORD", "") or None
        if bool(username) != bool(password):
            raise ValueError("MQTT_USERNAME and MQTT_PASSWORD must both be set or both be empty")
        battery_port = _int_env("CFE_BATTERY_PORT", 6868)
        mqtt_port = _int_env("MQTT_PORT", 1883)
        heartbeat_log_interval_min = _int_env("HEARTBEAT_LOG_INTERVAL_MIN", 60)
        if heartbeat_log_interval_min < 0:
            raise ValueError("HEARTBEAT_LOG_INTERVAL_MIN must be zero or positive")
        if not 1 <= battery_port <= 65535:
            raise ValueError("CFE_BATTERY_PORT must be between 1 and 65535")
        if not 1 <= mqtt_port <= 65535:
            raise ValueError("MQTT_PORT must be between 1 and 65535")
        mqtt_host = os.getenv("MQTT_HOST", "mqtt.example.com").strip()
        discovery_prefix = os.getenv("MQTT_DISCOVERY_PREFIX", "homeassistant").strip("/ ")
        base_topic = os.getenv("MQTT_BASE_TOPIC", "cfebms").strip("/ ")
        if not mqtt_host or not discovery_prefix or not base_topic:
            raise ValueError("MQTT_HOST, MQTT_DISCOVERY_PREFIX, and MQTT_BASE_TOPIC cannot be blank")
        return cls(
            battery_host=battery_host,
            battery_port=battery_port,
            connect_timeout=_float_env("CFE_CONNECT_TIMEOUT", 5.0),
            read_timeout=_float_env("CFE_READ_TIMEOUT", 10.0),
            reconnect_delay=_float_env("CFE_RECONNECT_DELAY", 5.0),
            stale_after=_float_env("CFE_STALE_AFTER", 30.0),
            telemetry_stale_after=_float_env("CFE_TELEMETRY_STALE_AFTER", 300.0),
            mqtt_host=mqtt_host,
            mqtt_port=mqtt_port,
            mqtt_username=username,
            mqtt_password=password,
            discovery_prefix=discovery_prefix,
            base_topic=base_topic,
            log_level=log_level,
            heartbeat_log_interval_min=heartbeat_log_interval_min,
        )
