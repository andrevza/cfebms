"""Build metadata written into container images at build time."""

from __future__ import annotations

import json
import logging
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

BUILD_INFO_PATH = Path("/usr/share/cfebms/build-metadata.json")
_UNKNOWN = "unknown"
_SHA_PATTERN = re.compile(r"^(?:[0-9a-fA-F]{40}|[0-9a-fA-F]{64})$")
_APP_VERSION_PATTERN = re.compile(r"^version:\s*[\"']?([^\"'\s#]+)", re.MULTILINE)


@dataclass(frozen=True, slots=True)
class BuildInfo:
    app_version: str = _UNKNOWN
    git_sha: str = _UNKNOWN
    built_at: str = _UNKNOWN
    source_state: str = _UNKNOWN

    @property
    def short_sha(self) -> str:
        return self.git_sha[:7] if _SHA_PATTERN.fullmatch(self.git_sha) else _UNKNOWN


def _valid_timestamp(value: object) -> str:
    if not isinstance(value, str) or not value:
        return _UNKNOWN
    try:
        timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return _UNKNOWN
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        return _UNKNOWN
    return timestamp.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _safe_sha(value: object) -> str:
    if isinstance(value, str) and _SHA_PATTERN.fullmatch(value):
        return value.lower()
    return _UNKNOWN


def _safe_source_state(value: object) -> str:
    if isinstance(value, str) and value in {"clean", "dirty", "unknown"}:
        return value
    return _UNKNOWN


def read_build_info(path: Path | None = None) -> BuildInfo:
    """Read baked metadata, returning unknown values if it is absent or invalid."""
    path = BUILD_INFO_PATH if path is None else path
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return BuildInfo()
    if not isinstance(raw, dict):
        return BuildInfo()
    version = raw.get("app_version")
    return BuildInfo(
        app_version=version.strip() if isinstance(version, str) and version.strip() else _UNKNOWN,
        git_sha=_safe_sha(raw.get("git_sha")),
        built_at=_valid_timestamp(raw.get("built_at")),
        source_state=_safe_source_state(raw.get("source_state")),
    )


def write_build_info(
    config_path: Path,
    output_path: Path,
    *,
    git_sha: str = _UNKNOWN,
    built_at: str | None = None,
    source_state: str = _UNKNOWN,
) -> BuildInfo:
    """Write build metadata using config.yaml as the App version authority."""
    config_text = config_path.read_text(encoding="utf-8")
    match = _APP_VERSION_PATTERN.search(config_text)
    app_version = match.group(1) if match else _UNKNOWN
    timestamp = built_at or datetime.now(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )
    info = BuildInfo(
        app_version=app_version,
        git_sha=_safe_sha(git_sha),
        built_at=_valid_timestamp(timestamp),
        source_state=_safe_source_state(source_state),
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(
            {
                "app_version": info.app_version,
                "git_sha": info.git_sha,
                "built_at": info.built_at,
                "source_state": info.source_state,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return info


def log_build_identity(log_level: str, *, path: Path | None = None) -> None:
    """Emit the process build identity once at service startup."""
    info = read_build_info(path)
    logger = logging.getLogger("cfebms")
    full_commit = info.git_sha if info.git_sha != _UNKNOWN else _UNKNOWN
    short_commit = info.short_sha
    commit_text = (
        f"{short_commit} ({full_commit})" if short_commit != _UNKNOWN else _UNKNOWN
    )
    logger.info("CFE BMS starting")
    logger.info("App version: %s", info.app_version)
    logger.info("Git commit: %s", commit_text)
    logger.info("Source state: %s", info.source_state)
    logger.info("Built at: %s", info.built_at)
    logger.info("Python runtime: %s", sys.version.split()[0])
    logger.info("Log level: %s", log_level)


def _write_from_environment() -> None:
    config_path = Path(os.environ.get("CFEBMS_BUILD_CONFIG", "/tmp/cfebms-config.yaml"))
    output_path = Path(os.environ.get("CFEBMS_BUILD_INFO_PATH", str(BUILD_INFO_PATH)))
    supplied_timestamp = os.environ.get("BUILD_TIMESTAMP", _UNKNOWN)
    info = write_build_info(
        config_path,
        output_path,
        git_sha=os.environ.get("BUILD_GIT_SHA", _UNKNOWN),
        built_at=supplied_timestamp if supplied_timestamp not in {"", _UNKNOWN} else None,
        source_state=os.environ.get("BUILD_SOURCE_STATE", _UNKNOWN),
    )
    print(
        f"Wrote CFE BMS build metadata: version={info.app_version}, "
        f"revision={info.git_sha}, source_state={info.source_state}, built_at={info.built_at}"
    )


if __name__ == "__main__":
    _write_from_environment()
