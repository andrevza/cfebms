from __future__ import annotations

import json
import os
import pwd
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path


_WORKER = """
import os
import sys
from pathlib import Path
from cfebms import supervisor
supervisor.OPTIONS_PATH = Path(os.environ.pop("CFEBMS_TEST_OPTIONS"))
supervisor.sys.argv = ["cfebms-supervisor", *os.environ.pop("CFEBMS_TEST_ARGS", "service").split()]
supervisor.main()
"""


def _test_directory() -> Path:
    path = Path(tempfile.mkdtemp(prefix="cfebms-options-test-", dir="/tmp"))
    path.chmod(0o755)
    return path


def _fake_service(path: Path) -> Path:
    executable = path / "bin" / "cfebms"
    executable.parent.mkdir(mode=0o755)
    executable.write_text(
        f"#!{sys.executable}\n"
        "import json, os, sys\n"
        "print(json.dumps({\n"
        "  'uid': os.getuid(), 'gid': os.getgid(), 'args': sys.argv[1:],\n"
        "  'battery_host': os.getenv('CFE_BATTERY_HOST'),\n"
        "  'battery_port': os.getenv('CFE_BATTERY_PORT'),\n"
        "  'mqtt_username_matches': os.getenv('MQTT_USERNAME') == os.getenv('CFEBMS_EXPECTED_USERNAME'),\n"
        "  'mqtt_password_matches': os.getenv('MQTT_PASSWORD') == os.getenv('CFEBMS_EXPECTED_PASSWORD'),\n"
        "}))\n"
    )
    executable.chmod(0o755)
    return executable


def _worker_env(path: Path, options_path: Path, expected: dict[str, str]) -> dict[str, str]:
    environ = os.environ.copy()
    environ.update(
        {
            "PATH": f"{path / 'bin'}{os.pathsep}{environ.get('PATH', '')}",
            "CFEBMS_TEST_OPTIONS": str(options_path),
            "CFEBMS_EXPECTED_USERNAME": expected.get("mqtt_username", ""),
            "CFEBMS_EXPECTED_PASSWORD": expected.get("mqtt_password", ""),
        }
    )
    return environ


def _run_worker(environ: dict[str, str], *, as_service_user: bool = False) -> subprocess.CompletedProcess[str]:
    preexec_fn = None
    if as_service_user:
        account = pwd.getpwnam("cfebms")

        def drop_before_exec() -> None:
            os.initgroups(account.pw_name, account.pw_gid)
            os.setgid(account.pw_gid)
            os.setuid(account.pw_uid)

        preexec_fn = drop_before_exec
    return subprocess.run(
        [sys.executable, "-c", _WORKER],
        env=environ,
        text=True,
        capture_output=True,
        timeout=10,
        preexec_fn=preexec_fn,
        check=False,
    )


def test_root_owned_restricted_supervisor_options_are_read_then_service_drops_uid() -> None:
    assert os.geteuid() == 0, "Run the permission regression in the Docker test image as root"
    test_dir = _test_directory()
    try:
        executable = _fake_service(test_dir)
        options = {
            "cfe_battery_host": "battery.example.com",
            "cfe_battery_port": 6868,
            "mqtt_username": "test-mqtt-user",
            "mqtt_password": "test-mqtt-password-do-not-log",
        }
        options_path = test_dir / "options.json"
        options_path.write_text(json.dumps(options))
        os.chown(options_path, 0, 0)
        options_path.chmod(0o600)
        metadata = options_path.stat()
        assert metadata.st_uid == 0
        assert stat.S_IMODE(metadata.st_mode) == 0o600

        account = pwd.getpwnam("cfebms")
        attempt = subprocess.run(
            [
                sys.executable,
                "-c",
                "from pathlib import Path; Path(__import__('os').environ['CFEBMS_TEST_OPTIONS']).read_text()",
            ],
            env={**os.environ, "CFEBMS_TEST_OPTIONS": str(options_path)},
            text=True,
            capture_output=True,
            timeout=10,
            preexec_fn=lambda: (os.initgroups(account.pw_name, account.pw_gid), os.setgid(account.pw_gid), os.setuid(account.pw_uid)),
            check=False,
        )
        assert attempt.returncode != 0
        assert "PermissionError" in attempt.stderr

        result = _run_worker(_worker_env(test_dir, options_path, options))
        assert result.returncode == 0, result.stderr
        launched = json.loads(result.stdout)
        assert launched["uid"] == 10001
        assert launched["gid"] == 10001
        assert launched["args"] == ["service"]
        assert launched["battery_host"] == "battery.example.com"
        assert launched["battery_port"] == "6868"
        assert launched["mqtt_username_matches"] is True
        assert launched["mqtt_password_matches"] is True
        assert options["mqtt_password"] not in result.stdout + result.stderr
        assert executable.is_file()
    finally:
        shutil.rmtree(test_dir)


def test_invalid_supervisor_options_fail_clearly_without_logging_credentials() -> None:
    assert os.geteuid() == 0, "Run the permission regression in the Docker test image as root"
    test_dir = _test_directory()
    try:
        _fake_service(test_dir)
        options_path = test_dir / "options.json"
        invalid_secret = "test-invalid-secret-do-not-log"
        options_path.write_text(
            json.dumps(
                {
                    "cfe_battery_host": "battery.example.com",
                    "mqtt_password": invalid_secret,
                }
            )
        )
        os.chown(options_path, 0, 0)
        options_path.chmod(0o600)
        result = _run_worker(_worker_env(test_dir, options_path, {}))
        assert result.returncode == 2
        assert "invalid application configuration" in result.stderr
        assert "MQTT_USERNAME and MQTT_PASSWORD must both be set" in result.stderr
        assert invalid_secret not in result.stdout + result.stderr
    finally:
        shutil.rmtree(test_dir)


def test_unreadable_supervisor_options_report_permission_error() -> None:
    assert os.geteuid() == 0, "Run the permission regression in the Docker test image as root"
    test_dir = _test_directory()
    try:
        options_path = test_dir / "options.json"
        options_path.write_text(json.dumps({"cfe_battery_host": "battery.example.com"}))
        os.chown(options_path, 0, 0)
        options_path.chmod(0o600)
        result = _run_worker(
            _worker_env(test_dir, options_path, {}),
            as_service_user=True,
        )
        assert result.returncode == 2
        assert "cannot read Home Assistant App options" in result.stderr
        assert "Permission denied" in result.stderr
    finally:
        shutil.rmtree(test_dir)


def test_standalone_environment_startup_also_drops_to_service_user() -> None:
    assert os.geteuid() == 0, "Run the permission regression in the Docker test image as root"
    test_dir = _test_directory()
    try:
        _fake_service(test_dir)
        absent_options = test_dir / "no-supervisor-options.json"
        environ = _worker_env(test_dir, absent_options, {})
        environ.update(
            {
                "CFE_BATTERY_HOST": "battery.example.net",
                "CFE_BATTERY_PORT": "6868",
                "MQTT_USERNAME": "",
                "MQTT_PASSWORD": "",
            }
        )
        result = _run_worker(environ)
        assert result.returncode == 0, result.stderr
        launched = json.loads(result.stdout)
        assert launched["uid"] == 10001
        assert launched["gid"] == 10001
        assert launched["args"] == ["service"]
        assert launched["battery_host"] == "battery.example.net"
    finally:
        shutil.rmtree(test_dir)
