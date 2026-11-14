"""Translate Home Assistant Supervisor options into the service's env config."""

from __future__ import annotations

import json
import os
import pwd
import sys
from pathlib import Path
from typing import Any, Mapping

from .config import Settings


OPTIONS_PATH = Path("/data/options.json")

OPTION_ENV = {
    "cfe_battery_host": "CFE_BATTERY_HOST",
    "cfe_battery_port": "CFE_BATTERY_PORT",
    "cfe_connect_timeout": "CFE_CONNECT_TIMEOUT",
    "cfe_read_timeout": "CFE_READ_TIMEOUT",
    "cfe_reconnect_delay": "CFE_RECONNECT_DELAY",
    "cfe_stale_after": "CFE_STALE_AFTER",
    "cfe_telemetry_stale_after": "CFE_TELEMETRY_STALE_AFTER",
    "mqtt_host": "MQTT_HOST",
    "mqtt_port": "MQTT_PORT",
    "mqtt_username": "MQTT_USERNAME",
    "mqtt_password": "MQTT_PASSWORD",
    "mqtt_discovery_prefix": "MQTT_DISCOVERY_PREFIX",
    "mqtt_base_topic": "MQTT_BASE_TOPIC",
    "log_level": "LOG_LEVEL",
    "heartbeat_log_interval_min": "HEARTBEAT_LOG_INTERVAL_MIN",
}

OPTIONAL_OPTIONS = {
    "mqtt_username",
    "mqtt_password",
    "cfe_connect_timeout",
    "cfe_read_timeout",
    "cfe_reconnect_delay",
    "cfe_stale_after",
    "cfe_telemetry_stale_after",
    "mqtt_discovery_prefix",
    "mqtt_base_topic",
    "log_level",
    "heartbeat_log_interval_min",
}


def apply_supervisor_options(options: Mapping[str, Any], environ: dict[str, str]) -> None:
    """Set existing application environment variables from Supervisor options."""
    for option, variable in OPTION_ENV.items():
        if option not in options or options[option] is None:
            continue
        value = options[option]
        if option in OPTIONAL_OPTIONS and value == "":
            continue
        environ[variable] = str(value)


def _drop_privileges() -> None:
    """Drop the startup process to the service account after config is loaded."""
    if os.geteuid() != 0:
        return
    account = pwd.getpwnam("cfebms")
    os.initgroups(account.pw_name, account.pw_gid)
    os.setgid(account.pw_gid)
    os.setuid(account.pw_uid)
    os.environ["HOME"] = account.pw_dir


def main() -> None:
    if OPTIONS_PATH.exists():
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
    if argv[1] == "service":
        try:
            Settings.from_env()
        except ValueError as exc:
            print(f"cfebms: invalid application configuration: {exc}", file=sys.stderr)
            raise SystemExit(2) from exc

    try:
        _drop_privileges()
    except (KeyError, OSError) as exc:
        print(f"cfebms: cannot switch to the non-root service account: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc

    os.execvpe("cfebms", argv, os.environ)


if __name__ == "__main__":
    main()
