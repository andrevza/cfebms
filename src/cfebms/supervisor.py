"""Translate Home Assistant Supervisor options into the service's env config."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Mapping


OPTIONS_PATH = Path("/data/options.json")

OPTION_ENV = {
    "cfe_battery_host": "CFE_BATTERY_HOST",
    "cfe_battery_port": "CFE_BATTERY_PORT",
    "cfe_connect_timeout": "CFE_CONNECT_TIMEOUT",
    "cfe_read_timeout": "CFE_READ_TIMEOUT",
    "cfe_reconnect_delay": "CFE_RECONNECT_DELAY",
    "cfe_stale_after": "CFE_STALE_AFTER",
    "mqtt_host": "MQTT_HOST",
    "mqtt_port": "MQTT_PORT",
    "mqtt_username": "MQTT_USERNAME",
    "mqtt_password": "MQTT_PASSWORD",
    "mqtt_discovery_prefix": "MQTT_DISCOVERY_PREFIX",
    "mqtt_base_topic": "MQTT_BASE_TOPIC",
    "log_level": "LOG_LEVEL",
    "heartbeat_log_interval_min": "HEARTBEAT_LOG_INTERVAL_MIN",
}


def apply_supervisor_options(options: Mapping[str, Any], environ: dict[str, str]) -> None:
    """Set existing application environment variables from Supervisor options."""
    for option, variable in OPTION_ENV.items():
        if option in options and options[option] is not None:
            environ[variable] = str(options[option])


def main() -> None:
    if OPTIONS_PATH.is_file():
        try:
            options = json.loads(OPTIONS_PATH.read_text(encoding="utf-8"))
            if not isinstance(options, dict):
                raise ValueError("Supervisor options must be a JSON object")
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            print(f"cfebms: cannot read Home Assistant App options: {exc}", file=sys.stderr)
            raise SystemExit(2) from exc
        apply_supervisor_options(options, os.environ)

    argv = ["cfebms", *sys.argv[1:]]
    if len(argv) == 1:
        argv.append("service")
    os.execvpe("cfebms", argv, os.environ)


if __name__ == "__main__":
    main()
