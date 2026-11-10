from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

from cfebms.build_info import (
    BuildInfo,
    log_build_identity,
    read_build_info,
    write_build_info,
)


def test_write_build_info_uses_app_manifest_and_preserves_full_sha(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text('name: "CFE BMS"\nversion: "0.1.8"\n', encoding="utf-8")
    output_path = tmp_path / "build-metadata.json"
    full_sha = "b2d881f528f0049cc4d4c7d5075275900fb65276"

    info = write_build_info(
        config_path,
        output_path,
        git_sha=full_sha,
        built_at="2026-11-10T12:00:00Z",
        source_state="dirty",
    )

    assert info == BuildInfo("0.1.8", full_sha, "2026-11-10T12:00:00Z", "dirty")
    assert info.short_sha == "b2d881f"
    assert json.loads(output_path.read_text(encoding="utf-8"))["git_sha"] == full_sha


def test_missing_or_invalid_metadata_is_reported_as_unknown(tmp_path: Path) -> None:
    assert read_build_info(tmp_path / "missing.json") == BuildInfo()

    config_path = tmp_path / "config.yaml"
    config_path.write_text("name: CFE BMS\n", encoding="utf-8")
    output_path = tmp_path / "build-metadata.json"
    write_build_info(
        config_path,
        output_path,
        git_sha="not-a-sha",
        built_at="not-a-timestamp",
        source_state="maybe-clean",
    )

    assert read_build_info(output_path) == BuildInfo()


def test_timestamp_is_normalized_to_utc_and_dirty_state_is_never_inferred(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text('version: "0.1.8"\n', encoding="utf-8")
    output_path = tmp_path / "build-metadata.json"
    info = write_build_info(
        config_path,
        output_path,
        git_sha="a" * 40,
        built_at="2026-11-10T14:00:00+02:00",
    )
    assert info.built_at == "2026-11-10T12:00:00Z"
    assert info.source_state == "unknown"


def test_missing_build_timestamp_is_generated_as_utc_during_metadata_creation(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text('version: "0.1.8"\n', encoding="utf-8")
    info = write_build_info(config_path, tmp_path / "build-metadata.json")

    assert info.built_at.endswith("Z")
    assert len(info.built_at) == 20


def test_startup_identity_reports_python_log_level_and_no_credentials(
    tmp_path: Path, caplog
) -> None:
    metadata = tmp_path / "build-metadata.json"
    metadata.write_text(
        json.dumps(
            {
                "app_version": "0.1.8",
                "git_sha": "b2d881f528f0049cc4d4c7d5075275900fb65276",
                "built_at": "2026-11-10T12:00:00Z",
                "source_state": "dirty",
            }
        ),
        encoding="utf-8",
    )

    with caplog.at_level(logging.INFO, logger="cfebms"):
        log_build_identity("DEBUG", path=metadata)

    messages = [record.getMessage() for record in caplog.records]
    assert messages == [
        "CFE BMS starting",
        "App version: 0.1.8",
        "Git commit: b2d881f (b2d881f528f0049cc4d4c7d5075275900fb65276)",
        "Source state: dirty",
        "Built at: 2026-11-10T12:00:00Z",
        f"Python runtime: {sys.version.split()[0]}",
        "Log level: DEBUG",
    ]
    assert "password" not in caplog.text.lower()
    assert "token" not in caplog.text.lower()


def test_cli_logs_identity_once_before_service_connection_attempt(
    monkeypatch, tmp_path: Path, caplog
) -> None:
    import cfebms.build_info
    import cfebms.cli
    import cfebms.service

    metadata = tmp_path / "build-metadata.json"
    metadata.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(cfebms.build_info, "BUILD_INFO_PATH", metadata)
    monkeypatch.setenv("CFE_BATTERY_HOST", "battery.invalid")
    monkeypatch.setenv("MQTT_HOST", "mqtt.invalid")
    monkeypatch.delenv("MQTT_USERNAME", raising=False)
    monkeypatch.delenv("MQTT_PASSWORD", raising=False)

    async def fake_run_service(_settings) -> None:
        logging.getLogger("cfebms.mqtt").info("Connecting to MQTT")

    monkeypatch.setattr(cfebms.service, "run_service", fake_run_service)

    with caplog.at_level(logging.INFO):
        assert cfebms.cli.main(["service"]) == 0

    messages = [record.getMessage() for record in caplog.records]
    assert messages.count("CFE BMS starting") == 1
    assert messages.index("Log level: INFO") < messages.index("Connecting to MQTT")
