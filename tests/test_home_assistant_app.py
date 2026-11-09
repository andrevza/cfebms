from __future__ import annotations

import hashlib
import json
import struct
from pathlib import Path

import pytest
import yaml

from cfebms import supervisor
from cfebms.config import Settings


ROOT = Path(__file__).parents[1]


def test_app_manifest_declares_supported_platforms_and_current_settings() -> None:
    manifest = yaml.safe_load((ROOT / "config.yaml").read_text())
    assert manifest["name"] == "CFE BMS"
    assert manifest["slug"] == "cfe_bms"
    assert manifest["description"] == "CFE Battery Management System"
    assert manifest["version"] == "0.1.5"
    assert manifest["url"] == "https://github.com/andrevza/cfebms"
    assert {"aarch64", "amd64"}.issubset(manifest["arch"])

    expected = {
        "cfe_battery_host": "",
        "cfe_battery_port": 6868,
        "mqtt_host": "",
        "mqtt_port": 1883,
        "mqtt_username": "",
        "mqtt_password": "",
    }
    assert manifest["options"] == expected
    assert set(manifest["schema"]) == set(supervisor.OPTION_ENV)
    assert set(expected).issubset(manifest["schema"])
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
    assert manifest["schema"]["mqtt_password"] == "password?"
    assert manifest["schema"]["cfe_connect_timeout"].endswith("?")
    assert manifest["schema"]["cfe_read_timeout"].endswith("?")
    assert manifest["schema"]["cfe_reconnect_delay"].endswith("?")
    assert manifest["schema"]["cfe_stale_after"].endswith("?")
    assert manifest["schema"]["mqtt_username"] == "str?"
    assert manifest["schema"]["mqtt_discovery_prefix"] == "str?"
    assert manifest["schema"]["mqtt_base_topic"] == "str?"
    assert manifest["schema"]["log_level"].endswith("?")
    assert manifest["schema"]["heartbeat_log_interval_min"] == "int(0,10080)?"
    assert set(manifest["arch"]) == {"aarch64", "amd64"}
    assert "privileged" not in manifest
    assert "host_network" not in manifest


def test_repository_metadata_points_to_cfebms() -> None:
    repository = yaml.safe_load((ROOT / "repository.yaml").read_text())
    assert repository["url"] == "https://github.com/andrevza/cfebms"


def test_build_and_icon_metadata_cover_requested_app_platforms() -> None:
    build = yaml.safe_load((ROOT / "build.yaml").read_text())
    assert set(build["build_from"]) == {"aarch64", "amd64"}
    assert set(build["build_from"].values()) == {
        "ghcr.io/home-assistant/base-python:3.12-alpine3.24"
    }
    icon = (ROOT / "icon.png").read_bytes()
    assert icon[:8] == b"\x89PNG\r\n\x1a\n"
    assert struct.unpack(">II", icon[16:24]) == (512, 512)


def test_configuration_translations_match_exactly_the_manifest_schema() -> None:
    manifest = yaml.safe_load((ROOT / "config.yaml").read_text())
    translations = yaml.safe_load((ROOT / "translations/en.yaml").read_text())
    configuration = translations["configuration"]

    assert set(configuration) == set(manifest["schema"])
    for key, text in configuration.items():
        assert set(text) == {"name", "description"}, key
        assert isinstance(text["name"], str) and text["name"].strip(), key
        assert isinstance(text["description"], str) and text["description"].strip(), key

    assert manifest["schema"]["mqtt_password"] == "password?"
    assert "CFE protocol heartbeat acknowledgements" in configuration[
        "heartbeat_log_interval_min"
    ]["description"]


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


def test_minimal_app_options_keep_omitted_advanced_python_defaults(monkeypatch) -> None:
    env = {}
    supervisor.apply_supervisor_options(
        {
            "cfe_battery_host": "battery.example.com",
            "cfe_battery_port": 6868,
            "mqtt_host": "mqtt.example.com",
            "mqtt_port": 1883,
            "mqtt_username": "",
            "mqtt_password": "",
        },
        env,
    )
    monkeypatch.setattr("os.environ", env)
    settings = Settings.from_env()
    assert settings.connect_timeout == 5.0
    assert settings.read_timeout == 10.0
    assert settings.reconnect_delay == 5.0
    assert settings.stale_after == 30.0
    assert settings.discovery_prefix == "homeassistant"
    assert settings.base_topic == "cfebms"
    assert settings.log_level == "INFO"
    assert settings.heartbeat_log_interval_min == 60


def test_null_or_empty_optional_options_do_not_replace_python_defaults(monkeypatch) -> None:
    env = {}
    supervisor.apply_supervisor_options(
        {
            "cfe_battery_host": "battery.example.com",
            "mqtt_host": "mqtt.example.com",
            "mqtt_username": "",
            "mqtt_password": "",
            "cfe_connect_timeout": None,
            "mqtt_discovery_prefix": "",
            "mqtt_base_topic": None,
            "log_level": "",
        },
        env,
    )
    monkeypatch.setattr("os.environ", env)
    settings = Settings.from_env()
    assert settings.mqtt_username is None
    assert settings.mqtt_password is None
    assert settings.connect_timeout == 5.0
    assert settings.discovery_prefix == "homeassistant"
    assert settings.base_topic == "cfebms"
    assert settings.log_level == "INFO"


def test_optional_saved_advanced_app_options_override_python_defaults(monkeypatch) -> None:
    env = {}
    supervisor.apply_supervisor_options(
        {
            "cfe_battery_host": "battery.example.com",
            "mqtt_host": "mqtt.example.com",
            "cfe_connect_timeout": 8.5,
            "cfe_read_timeout": 12.0,
            "cfe_reconnect_delay": 7.0,
            "cfe_stale_after": 45.0,
            "mqtt_discovery_prefix": "ha_custom",
            "mqtt_base_topic": "battery/cfe",
            "log_level": "DEBUG",
            "heartbeat_log_interval_min": 0,
        },
        env,
    )
    monkeypatch.setattr("os.environ", env)
    settings = Settings.from_env()
    assert settings.connect_timeout == 8.5
    assert settings.read_timeout == 12.0
    assert settings.reconnect_delay == 7.0
    assert settings.stale_after == 45.0
    assert settings.discovery_prefix == "ha_custom"
    assert settings.base_topic == "battery/cfe"
    assert settings.log_level == "DEBUG"
    assert settings.heartbeat_log_interval_min == 0


def test_invalid_advanced_option_keeps_clear_python_validation(monkeypatch) -> None:
    env = {}
    supervisor.apply_supervisor_options(
        {
            "cfe_battery_host": "battery.example.com",
            "mqtt_host": "mqtt.example.com",
            "cfe_connect_timeout": "not-a-number",
        },
        env,
    )
    monkeypatch.setattr("os.environ", env)
    with pytest.raises(ValueError, match="CFE_CONNECT_TIMEOUT must be numeric"):
        Settings.from_env()


def test_app_docs_and_changelog_cover_options_and_app_versions() -> None:
    docs = (ROOT / "DOCS.md").read_text()
    changelog = (ROOT / "CHANGELOG.md").read_text()
    for option in supervisor.OPTION_ENV:
        assert f"`{option}`" in docs
    for version in ("0.1.0", "0.1.1", "0.1.2", "0.1.3"):
        assert f"## {version}" in changelog


def test_app_entrypoint_executes_service_and_loads_supervisor_options(tmp_path, monkeypatch) -> None:
    options_path = tmp_path / "options.json"
    options_path.write_text(json.dumps({"cfe_battery_host": "battery.example.com"}))
    monkeypatch.setattr(supervisor, "OPTIONS_PATH", options_path)
    monkeypatch.setattr(supervisor.sys, "argv", ["cfebms-supervisor"])
    monkeypatch.setattr(supervisor.os, "environ", {})
    monkeypatch.setattr(supervisor, "_drop_privileges", lambda: None)
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
    compose = (ROOT / "docker-compose.yml").read_text()
    assert 'CMD ["/run.sh", "service"]' in dockerfile
    assert 'ENTRYPOINT ["/run.sh"]' not in dockerfile
    assert "adduser -D -h /home/cfebms -u 10001 -G cfebms cfebms" in dockerfile
    assert "groupadd --gid 10001 cfebms" in dockerfile
    assert "USER cfebms" not in dockerfile
    assert 'entrypoint: ["/run.sh"]' in compose
    assert "exec python -m cfebms.supervisor \"$@\"" in run_script
