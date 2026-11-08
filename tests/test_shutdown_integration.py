"""SIGTERM integration test for the installed cfebms service entrypoint."""

from __future__ import annotations

import os
import select
import shutil
import signal
import socket
import struct
import subprocess
import threading
import time


def _recv_exact(connection: socket.socket, size: int) -> bytes:
    data = bytearray()
    while len(data) < size:
        chunk = connection.recv(size - len(data))
        if not chunk:
            raise EOFError
        data.extend(chunk)
    return bytes(data)


def _recv_mqtt_packet(connection: socket.socket) -> tuple[int, bytes]:
    first = _recv_exact(connection, 1)[0]
    remaining = 0
    multiplier = 1
    while True:
        digit = _recv_exact(connection, 1)[0]
        remaining += (digit & 127) * multiplier
        if not digit & 128:
            break
        multiplier *= 128
    return first, _recv_exact(connection, remaining)


def _encode_remaining_length(length: int) -> bytes:
    encoded = bytearray()
    while True:
        digit = length % 128
        length //= 128
        if length:
            digit |= 128
        encoded.append(digit)
        if not length:
            return bytes(encoded)


class _TestBroker:
    def __init__(self) -> None:
        self.listener = socket.socket()
        self.listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.listener.bind(("127.0.0.1", 0))
        self.listener.listen(1)
        self.listener.settimeout(5)
        self.port = self.listener.getsockname()[1]
        self.publishes: list[tuple[str, bytes]] = []
        self.error: BaseException | None = None
        self.thread = threading.Thread(target=self._serve, daemon=True)

    def start(self) -> None:
        self.thread.start()

    def close(self) -> None:
        self.listener.close()
        self.thread.join(timeout=1)

    def _serve(self) -> None:
        try:
            connection, _ = self.listener.accept()
            with connection:
                connection.settimeout(8)
                while True:
                    header, body = _recv_mqtt_packet(connection)
                    packet_type = header >> 4
                    if packet_type == 1:  # CONNECT
                        connection.sendall(b"\x20\x02\x00\x00")
                    elif packet_type == 8:  # SUBSCRIBE
                        packet_id = body[:2]
                        connection.sendall(b"\x90\x03" + packet_id + b"\x01")
                    elif packet_type == 3:  # PUBLISH
                        topic_length = struct.unpack(">H", body[:2])[0]
                        topic = body[2 : 2 + topic_length].decode()
                        qos = (header >> 1) & 0x03
                        offset = 2 + topic_length
                        packet_id = body[offset : offset + 2] if qos else b""
                        if qos:
                            offset += 2
                        self.publishes.append((topic, body[offset:]))
                        if qos == 1:
                            connection.sendall(b"\x40\x02" + packet_id)
                    elif packet_type == 12:  # PINGREQ
                        connection.sendall(b"\xd0\x00")
                    elif packet_type == 14:  # DISCONNECT
                        return
        except (EOFError, OSError, TimeoutError) as exc:
            if not isinstance(exc, EOFError):
                self.error = exc
        except BaseException as exc:  # surface thread failures in the test
            self.error = exc


class _BatteryEndpoint:
    def __init__(self) -> None:
        self.listener = socket.socket()
        self.listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.listener.bind(("127.0.0.1", 0))
        self.listener.listen(1)
        self.listener.settimeout(8)
        self.port = self.listener.getsockname()[1]
        self.closed = threading.Event()
        self.thread = threading.Thread(target=self._serve, daemon=True)

    def start(self) -> None:
        self.thread.start()

    def close(self) -> None:
        self.listener.close()
        self.thread.join(timeout=1)

    def _serve(self) -> None:
        try:
            connection, _ = self.listener.accept()
            with connection:
                connection.settimeout(6)
                while connection.recv(1024):
                    pass
        except (OSError, TimeoutError):
            pass
        finally:
            self.closed.set()


def test_sigterm_through_installed_entrypoint_completes_gracefully() -> None:
    entrypoint = shutil.which("cfebms")
    assert entrypoint is not None
    broker = _TestBroker()
    battery = _BatteryEndpoint()
    broker.start()
    battery.start()
    environment = os.environ.copy()
    environment.update(
        {
            "CFE_BATTERY_HOST": "127.0.0.1",
            "CFE_BATTERY_PORT": str(battery.port),
            "CFE_CONNECT_TIMEOUT": "1",
            "CFE_READ_TIMEOUT": "1",
            "CFE_RECONNECT_DELAY": "0.2",
            "MQTT_HOST": "127.0.0.1",
            "MQTT_PORT": str(broker.port),
            "LOG_LEVEL": "INFO",
            "PYTHONUNBUFFERED": "1",
        }
    )
    process = subprocess.Popen(
        [entrypoint, "service"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        env=environment,
        bufsize=1,
    )
    output: list[str] = []
    try:
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            ready, _, _ = select.select([process.stdout], [], [], min(0.2, deadline - time.monotonic()))
            if not ready:
                if process.poll() is not None:
                    break
                continue
            line = process.stdout.readline()
            if line:
                output.append(line)
                if "Connected to CFE battery" in line and "MQTT connected to broker" in "".join(output):
                    break
            elif process.poll() is not None:
                break
        assert process.poll() is None, "service exited before SIGTERM: " + "".join(output)
        assert "Connected to CFE battery" in "".join(output)
        process.send_signal(signal.SIGTERM)
        remaining, _ = process.communicate(timeout=9)
        output.append(remaining)
        assert process.returncode == 0, "service exit code was %s: %s" % (process.returncode, "".join(output))
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=2)
        broker.close()
        battery.close()

    logs = "".join(output)
    assert "Shutdown requested (SIGTERM)" in logs
    assert "Battery communication stopped" in logs
    assert "CFE battery TCP connection closed" in logs
    assert "MQTT offline availability published and delivery completed" in logs
    assert "MQTT disconnected gracefully" in logs
    assert "Graceful shutdown complete" in logs
    assert any(topic == "cfebms/availability" and payload == b"offline" for topic, payload in broker.publishes)
    assert any(topic == "cfebms/availability/pack_1_v_pack" and payload == b"offline" for topic, payload in broker.publishes)
    assert battery.closed.is_set()
    assert broker.error is None
