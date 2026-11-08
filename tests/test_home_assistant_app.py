from __future__ import annotations

import hashlib
import json
import struct
from pathlib import Path

import yaml

from cfebms import supervisor
from cfebms.config import Settings


ROOT = Path(__file__).parents[1]


def test_app_manifest_declares_supported_platforms_and_current_settings() -> None:
    manifest = yaml.safe_load((ROOT / "config.yaml").read_text())
    assert manifest["name"] == "CFE BMS"
    assert manifest["slug"] == "cfe_bms"
    assert manifest["description"] == "CFE Battery Management System"
    assert manifest["version"] == "0.1.0"
    assert manifest["url"] == "https://github.com/andrevza/cfebms"
    assert {"aarch64", "amd64"}.issubset(manifest["arch"])

    expected = {
        "cfe_battery_host": "",
        "cfe_battery_port": 6868,
        "cfe_connect_timeout": 5.0,
        "cfe_read_timeout": 10.0,
        "cfe_reconnect_delay": 5.0,
        "cfe_stale_after": 30.0,
        "mqtt_host": "mqtt.example.com",
        "mqtt_port": 1883,
        "mqtt_username": "",
        "mqtt_password": "",
        "mqtt_discovery_prefix": "homeassistant",
        "mqtt_base_topic": "cfebms",
        "log_level": "INFO",
        "heartbeat_log_interval_min": 60,
    }
    assert manifest["options"] == expected
    assert set(manifest["schema"]) == set(expected)
    assert set(supervisor.OPTION_ENV) == set(expected)
    assert set(supervisor.OPTION_ENV.values()) == {
        "CFE_BATTERY_HOST",
        "CFE_BATTERY_PORT",
        "CFE_CONNECT_TIMEOUT",
        "CFE_READ_TIMEOUT",
        "CFE_RECONNECT_DELAY",
        "CFE_STALE_AFTER",
        "MQTT_HOST",
        "MQTT_PORT",
        "MQTT_USERNAME",
        "MQTT_PASSWORD",
        "MQTT_DISCOVERY_PREFIX",
        "MQTT_BASE_TOPIC",
        "LOG_LEVEL",
        "HEARTBEAT_LOG_INTERVAL_MIN",
    }
    assert manifest["schema"]["mqtt_password"] == "password"
    assert set(manifest["arch"]) == {"aarch64", "amd64"}
    assert "privileged" not in manifest
    assert "host_network" not in manifest


def test_repository_metadata_points_to_cfebms() -> None:
    repository = yaml.safe_load((ROOT / "repository.yaml").read_text())
    assert repository["url"] == "https://github.com/andrevza/cfebms"


def test_build_and_icon_metadata_cover_requested_app_platforms() -> None:
    build = yaml.safe_load((ROOT / "build.yaml").read_text())
    assert set(build["build_from"]) == {"aarch64", "amd64"}
    icon = (ROOT / "icon.png").read_bytes()
    assert icon[:8] == b"\x89PNG\r\n\x1a\n"
    assert struct.unpack(">II", icon[16:24]) == (512, 512)


def test_approved_branding_files_are_installed_without_modification() -> None:
    expected_assets = {
        "logo.png": "7e6d36d20e03ddb34eaefd04e7d7481cc2359e3c5d271cb9b9abf49b335de71b",
        "docs/images/cfebms-banner.png": "6a623edbd86e5d431af0ecb8f1eb2bb558574ffc18a2abe2cff37d953248dbb9",
    }
    for name, expected_digest in expected_assets.items():
        image = (ROOT / name).read_bytes()
        assert image[:8] == b"\x89PNG\r\n\x1a\n"
        assert hashlib.sha256(image).hexdigest() == expected_digest


def test_supervisor_options_map_to_existing_environment_and_credentials(monkeypatch) -> None:
    env = {}
    supervisor.apply_supervisor_options(
        {
            "cfe_battery_host": "battery.example.com",
            "cfe_battery_port": 6868,
            "mqtt_username": "mqtt_user",
            "mqtt_password": "secret-value",
            "heartbeat_log_interval_min": 0,
        },
        env,
    )
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    settings = Settings.from_env()
    assert settings.battery_host == "battery.example.com"
    assert settings.battery_port == 6868
    assert settings.mqtt_username == "mqtt_user"
    assert settings.mqtt_password == "secret-value"
    assert settings.heartbeat_log_interval_min == 0


def test_app_entrypoint_executes_service_and_loads_supervisor_options(tmp_path, monkeypatch) -> None:
    options_path = tmp_path / "options.json"
    options_path.write_text(json.dumps({"cfe_battery_host": "battery.example.com"}))
    monkeypatch.setattr(supervisor, "OPTIONS_PATH", options_path)
    monkeypatch.setattr(supervisor.sys, "argv", ["cfebms-supervisor"])
    monkeypatch.setattr(supervisor.os, "environ", {})
    invoked = {}

    def fake_execvpe(file, argv, env):
        invoked.update(file=file, argv=argv, env=dict(env))

    monkeypatch.setattr(supervisor.os, "execvpe", fake_execvpe)
    supervisor.main()
    assert invoked["file"] == "cfebms"
    assert invoked["argv"] == ["cfebms", "service"]
    assert invoked["env"]["CFE_BATTERY_HOST"] == "battery.example.com"


def test_runtime_container_uses_supervisor_wrapper() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text()
    run_script = (ROOT / "run.sh").read_text()
    assert 'ENTRYPOINT ["/run.sh"]' in dockerfile
    assert 'CMD ["service"]' in dockerfile
    assert dockerfile.rstrip().endswith('CMD ["service"]')
    assert "exec python -m cfebms.supervisor \"$@\"" in run_script
