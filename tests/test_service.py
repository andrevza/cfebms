from __future__ import annotations

import asyncio
import logging
import signal
import time

import cfebms.service as service_module
from cfebms.service import reconnect_loop, run_service
from cfebms.config import Settings
from cfebms.frames import crc16_modbus
from cfebms.protocol import OBSERVED_INITIAL_SEQUENCE
from cfebms.service import BatteryService


class FakeWriter:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True

    async def wait_closed(self) -> None:
        return None


def test_connection_loop_retries_after_failure_and_shuts_down() -> None:
    stop = asyncio.Event()
    attempts = 0
    writer = FakeWriter()

    async def connect():
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise OSError("simulated offline endpoint")
        return object(), writer

    async def session(reader, current_writer):
        assert current_writer is writer
        stop.set()

    asyncio.run(reconnect_loop(connect, session, stop=stop, retry_delay=0.001))
    assert attempts == 2
    assert writer.closed


def test_connection_loop_logs_exception_type_details_and_retry(caplog) -> None:
    class EmptyRefusal(ConnectionRefusedError):
        def __str__(self):
            return ""

    stop = asyncio.Event()
    attempts = 0
    writer = FakeWriter()

    async def connect():
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise EmptyRefusal()
        return object(), writer

    async def session(reader, current_writer):
        stop.set()

    with caplog.at_level(logging.INFO):
        asyncio.run(reconnect_loop(connect, session, stop=stop, retry_delay=0.001))

    assert "Battery TCP connection failed: EmptyRefusal: no additional details" in caplog.text
    assert "EmptyRefusal: no additional details" in caplog.text
    assert "consecutive failures: 1). Retrying in 0.001 seconds." in caplog.text


def test_session_echoes_each_valid_heartbeat_exactly(caplog) -> None:
    variant = bytearray(OBSERVED_INITIAL_SEQUENCE)
    variant[9] ^= 1
    variant[-3:-1] = crc16_modbus(variant[:-3]).to_bytes(2, "little")
    variant = bytes(variant)

    class Reader:
        chunks = [OBSERVED_INITIAL_SEQUENCE, variant, b""]

        async def read(self, size):
            return self.chunks.pop(0)

    class Writer:
        def __init__(self):
            self.writes = []

        def write(self, value):
            self.writes.append(value)

        async def drain(self):
            return None

        def close(self):
            return None

        async def wait_closed(self):
            return None

    class Publisher:
        def publish_connection(self, connected):
            pass

        def mark_stale(self, **kwargs):
            pass

        def mark_all_unavailable(self):
            pass

        def publish_values(self, values):
            pass

    async def run():
        service = BatteryService(Settings(battery_host="battery.invalid"), Publisher())
        writer = Writer()
        try:
            await service._session(Reader(), writer)
        except ConnectionError:
            pass
        return writer.writes

    with caplog.at_level(logging.INFO):
        assert asyncio.run(run()) == [OBSERVED_INITIAL_SEQUENCE, variant]
    assert "First CRC-valid CFE heartbeat received" in caplog.text
    assert "First CFE heartbeat acknowledged" in caplog.text


def test_signal_shutdown_is_idempotent_for_sigterm_and_sigint(caplog) -> None:
    class Publisher:
        pass

    async def run(signum):
        service = BatteryService(Settings(battery_host="battery.invalid"), Publisher())
        writer = FakeWriter()
        service._writer = writer
        service.handle_signal(signum)
        service.handle_signal(signum)
        return service, writer

    with caplog.at_level(logging.INFO):
        term_service, term_writer = asyncio.run(run(signal.SIGTERM))
        int_service, int_writer = asyncio.run(run(signal.SIGINT))
    assert term_service.stop.is_set() and int_service.stop.is_set()
    assert term_writer.closed and int_writer.closed
    assert caplog.text.count("Shutdown requested (SIGTERM)") == 1
    assert caplog.text.count("Shutdown requested (SIGINT)") == 1


def test_disconnected_shutdown_logs_disconnect_once(caplog) -> None:
    async def run():
        service = BatteryService(Settings(battery_host="battery.invalid"), object())
        service.request_shutdown("SIGINT")
        service.log_shutdown_disconnect_if_needed()
        service.log_shutdown_disconnect_if_needed()

    with caplog.at_level(logging.INFO):
        asyncio.run(run())
    assert caplog.text.count("CFE battery disconnected") == 1


def test_reconnect_loop_does_not_retry_after_shutdown_during_connect() -> None:
    stop = asyncio.Event()
    attempts = 0

    async def connect():
        nonlocal attempts
        attempts += 1
        stop.set()
        raise ConnectionRefusedError("stopped")

    async def session(reader, writer):
        raise AssertionError("session must not start after shutdown")

    asyncio.run(reconnect_loop(connect, session, stop=stop, retry_delay=0.001))
    assert attempts == 1


def test_periodic_info_callback_does_not_change_battery_retry_delay() -> None:
    stop = asyncio.Event()
    attempts = 0
    second_attempt_at = None
    start = None

    async def connect():
        nonlocal attempts, second_attempt_at, start
        attempts += 1
        if attempts == 1:
            start = asyncio.get_running_loop().time()
            raise ConnectionRefusedError("offline")
        second_attempt_at = asyncio.get_running_loop().time()
        return object(), FakeWriter()

    async def session(reader, writer):
        stop.set()

    asyncio.run(
        reconnect_loop(
            connect,
            session,
            stop=stop,
            retry_delay=0.06,
            on_periodic_info=lambda: None,
        )
    )
    assert attempts == 2
    assert second_attempt_at - start >= 0.05


def test_three_failed_connections_reset_counter_after_success(caplog) -> None:
    stop = asyncio.Event()
    attempts = 0
    connected = 0

    async def connect():
        nonlocal attempts
        attempts += 1
        if attempts <= 3:
            raise ConnectionRefusedError("offline")
        return object(), FakeWriter()

    async def session(reader, writer):
        stop.set()

    def on_connected():
        nonlocal connected
        connected += 1

    with caplog.at_level(logging.WARNING):
        asyncio.run(
            reconnect_loop(
                connect,
                session,
                stop=stop,
                retry_delay=0.001,
                on_connected=on_connected,
            )
        )

    assert attempts == 4
    assert connected == 1
    assert "consecutive failures: 1). Retrying" in caplog.text
    assert "consecutive failures: 2). Retrying" in caplog.text
    assert "consecutive failures: 3). Retrying" in caplog.text


def test_disconnection_starts_new_failure_sequence(caplog) -> None:
    stop = asyncio.Event()
    attempts = 0
    connected = 0

    async def connect():
        nonlocal attempts
        attempts += 1
        if attempts == 2:
            raise ConnectionRefusedError("reconnect refused")
        return object(), FakeWriter()

    async def session(reader, writer):
        if attempts == 1:
            raise ConnectionError("established stream dropped")
        stop.set()

    def on_connected():
        nonlocal connected
        connected += 1

    with caplog.at_level(logging.WARNING):
        asyncio.run(
            reconnect_loop(
                connect,
                session,
                stop=stop,
                retry_delay=0.001,
                on_connected=on_connected,
            )
        )

    assert attempts == 3
    assert connected == 2
    assert "connection lost or closed: ConnectionError: established stream dropped (consecutive failures: 1)" in caplog.text
    assert "ConnectionRefusedError: reconnect refused (consecutive failures: 2)" in caplog.text


def test_repeated_successful_reconnects_do_not_accumulate_failures(caplog) -> None:
    stop = asyncio.Event()
    attempts = 0
    connected = 0

    async def connect():
        nonlocal attempts
        attempts += 1
        return object(), FakeWriter()

    async def session(reader, writer):
        if attempts == 3:
            stop.set()
        else:
            raise ConnectionError("stream dropped")

    def on_connected():
        nonlocal connected
        connected += 1

    with caplog.at_level(logging.WARNING):
        asyncio.run(
            reconnect_loop(
                connect,
                session,
                stop=stop,
                retry_delay=0.001,
                on_connected=on_connected,
            )
        )

    assert attempts == connected == 3
    assert caplog.text.count("consecutive failures: 1)") == 2
    assert "consecutive failures: 2)" not in caplog.text


def test_successful_connection_shutdown_does_not_reconnect() -> None:
    stop = asyncio.Event()
    attempts = 0

    async def connect():
        nonlocal attempts
        attempts += 1
        return object(), FakeWriter()

    async def session(reader, writer):
        stop.set()

    asyncio.run(reconnect_loop(connect, session, stop=stop, retry_delay=0.001))
    assert attempts == 1


def test_session_disconnect_resets_protocol_counters_but_keeps_latest_values() -> None:
    class Reader:
        async def read(self, size):
            return b""

    class Writer(FakeWriter):
        def is_closing(self):
            return self.closed

        def write(self, data):
            pass

        async def drain(self):
            pass

    class Publisher:
        connected = asyncio.Event()

        def publish_connection(self, connected):
            pass

        def mark_stale(self, **kwargs):
            pass

        def mark_all_unavailable(self):
            pass

    async def run():
        service = BatteryService(Settings(battery_host="battery.invalid"), Publisher())
        service._session_frame_counts.update(HEARTBEAT=12, STATUS=3, SUMMARY=4, DETAIL=5)
        service._interval_frame_counts.update(HEARTBEAT=12, STATUS=3, SUMMARY=4, DETAIL=5)
        service._latest_soc = 61
        service._latest_voltage = 49.68
        previous_baseline = service.last_heartbeat_monotonic
        try:
            await service._session(Reader(), Writer())
        except ConnectionError:
            pass
        return service, previous_baseline

    service, previous_baseline = asyncio.run(run())
    assert service._session_frame_counts == dict.fromkeys(service_module.FRAME_TYPES, 0)
    assert service._interval_frame_counts == dict.fromkeys(service_module.FRAME_TYPES, 0)
    assert service.last_heartbeat_monotonic >= previous_baseline
    assert service._latest_soc == 61
    assert service._latest_voltage == 49.68


def test_reconnect_restarts_operational_heartbeat_baseline() -> None:
    class Publisher:
        connected = asyncio.Event()

    service = BatteryService(Settings(battery_host="battery.invalid"), Publisher())
    service._session_frame_counts.update(HEARTBEAT=6, STATUS=2, SUMMARY=3, DETAIL=4)
    service._interval_frame_counts.update(HEARTBEAT=6, STATUS=2, SUMMARY=3, DETAIL=4)
    service._latest_soc = 50
    service.last_heartbeat_monotonic -= 100
    service._on_connection_established()
    assert service._session_frame_counts == dict.fromkeys(service_module.FRAME_TYPES, 0)
    assert service._interval_frame_counts == dict.fromkeys(service_module.FRAME_TYPES, 0)
    assert service._next_heartbeat_deadline is not None
    assert abs(service._next_heartbeat_deadline - service.last_heartbeat_monotonic - 3600) < 0.001
    assert service._latest_soc == 50


def test_session_does_not_emit_legacy_telemetry_summary_info(caplog) -> None:
    class Reader:
        def __init__(self, frame):
            self.chunks = [frame, b""]

        async def read(self, size):
            return self.chunks.pop(0)

    class Writer(FakeWriter):
        def is_closing(self):
            return self.closed

    class Publisher:
        connected = asyncio.Event()

        def publish_connection(self, connected):
            pass

        def mark_stale(self, **kwargs):
            pass

        def mark_all_unavailable(self):
            pass

        def publish_values(self, values):
            pass

    frame = bytearray(73)
    frame[0] = 0x68
    frame[-1] = 0x16
    frame[-3:-1] = crc16_modbus(frame[:-3]).to_bytes(2, "little")
    async def run():
        service = BatteryService(Settings(battery_host="battery.invalid"), Publisher())
        try:
            await service._session(Reader(bytes(frame)), Writer())
        except ConnectionError:
            pass

    with caplog.at_level(logging.INFO):
        asyncio.run(run())
    assert "First valid CFE SUMMARY frame received" in caplog.text
    assert "Telemetry summary:" not in caplog.text


def test_run_service_shuts_down_cleanly_without_traceback(monkeypatch, caplog) -> None:
    class Publisher:
        def __init__(self, settings):
            self.shutdowns = 0

        async def start(self, **kwargs):
            return None

        async def graceful_shutdown(self):
            self.shutdowns += 1
            logging.getLogger("cfebms.mqtt").info("Graceful shutdown complete")

    class Service:
        instance = None

        def __init__(self, settings, publisher):
            self.stop = asyncio.Event()
            self.publisher = publisher
            type(self).instance = self

        async def run(self):
            self.stop.set()

        def handle_signal(self, signum):
            self.stop.set()

        def request_shutdown(self, reason):
            self.stop.set()

        def log_shutdown_disconnect_if_needed(self):
            pass

    monkeypatch.setattr(service_module, "MQTTPublisher", Publisher)
    monkeypatch.setattr(service_module, "BatteryService", Service)
    with caplog.at_level(logging.INFO):
        asyncio.run(run_service(Settings(battery_host="battery.invalid")))
    assert Service.instance.publisher.shutdowns == 1
    assert "Graceful shutdown complete" in caplog.text
    assert "Traceback" not in caplog.text


def test_operational_heartbeat_reports_health_counts_values_and_elapsed_interval(caplog) -> None:
    class Publisher:
        def __init__(self):
            self.connected = asyncio.Event()
            self.connected.set()

    class Writer:
        def is_closing(self):
            return False

    service = BatteryService(
        Settings(battery_host="battery.invalid", heartbeat_log_interval_min=60),
        Publisher(),
    )
    service._writer = Writer()
    deadline = service._next_heartbeat_deadline
    assert deadline is not None
    now = deadline + 0.7
    service._last_rx_monotonic = now
    service._last_valid_telemetry_monotonic = now
    service._session_frame_counts.update(HEARTBEAT=12, STATUS=3, SUMMARY=4, DETAIL=4)
    service._interval_frame_counts.update(HEARTBEAT=12, STATUS=3, SUMMARY=4, DETAIL=4)
    service._latest_soc = 7
    service._latest_voltage = 49.68
    service._latest_battery_rtc = "2026-11-10T10:00:00"

    with caplog.at_level(logging.INFO):
        service.log_periodic_info(now=now)

    assert (
        "CFE healthy: battery connected, MQTT connected, 12 heartbeats, 3 statuses, "
        "4 summaries, 4 detail frames, SOC=7%, voltage=49.68V, "
        "battery_rtc=2026-11-10T10:00:00 (interval=3600.7s)"
    ) in caplog.text
    assert service._session_frame_counts["HEARTBEAT"] == 12
    assert service._interval_frame_counts == dict.fromkeys(service_module.FRAME_TYPES, 0)


def test_operational_health_summary_supports_five_minute_interval(caplog) -> None:
    class Publisher:
        connected = asyncio.Event()

    service = BatteryService(
        Settings(battery_host="battery.invalid", heartbeat_log_interval_min=5),
        Publisher(),
    )
    deadline = service._next_heartbeat_deadline
    assert deadline is not None
    service.log_periodic_info(now=deadline - 0.1)
    assert "CFE healthy:" not in caplog.text

    with caplog.at_level(logging.INFO):
        service.log_periodic_info(now=deadline)
    assert "(interval=300.0s)" in caplog.text


def test_battery_rtc_is_diagnostic_only_and_updates_health_report() -> None:
    rtc = 1700000000

    class Reader:
        async def read(self, size):
            nonlocal frame_sent
            if frame_sent:
                return b""
            frame_sent = True
            return frame

    class Writer(FakeWriter):
        async def drain(self):
            return None

    class Publisher:
        def __init__(self):
            self.values = []

        def publish_connection(self, connected):
            pass

        def mark_stale(self, **kwargs):
            pass

        def mark_all_unavailable(self):
            pass

        def publish_values(self, values):
            self.values.append(dict(values))

    frame = bytearray(_valid_frame(73, voltage=5056, soc=10))
    frame[9:13] = rtc.to_bytes(4, "little")
    frame[-3:-1] = crc16_modbus(frame[:-3]).to_bytes(2, "little")
    frame = bytes(frame)
    frame_sent = False
    publisher = Publisher()
    service = BatteryService(Settings(battery_host="battery.invalid"), publisher)

    async def run():
        try:
            await service._session(Reader(), Writer())
        except ConnectionError:
            pass

    asyncio.run(run())

    assert service._latest_battery_rtc == "2023-11-14T22:13:20+00:00"
    assert publisher.values
    assert all("battery_rtc_iso" not in values for values in publisher.values)
    assert all("battery_rtc_raw" not in values for values in publisher.values)


def test_operational_heartbeat_is_degraded_when_telemetry_is_stale(caplog) -> None:
    class Publisher:
        def __init__(self):
            self.connected = asyncio.Event()
            self.connected.set()

    class Writer:
        def is_closing(self):
            return False

    service = BatteryService(
        Settings(battery_host="battery.invalid", heartbeat_log_interval_min=1),
        Publisher(),
    )
    service._writer = Writer()
    deadline = service._next_heartbeat_deadline
    assert deadline is not None
    service._last_rx_monotonic = deadline
    service._last_valid_telemetry_monotonic = deadline - service.settings.stale_after - 1

    with caplog.at_level(logging.INFO):
        service.log_periodic_info(now=deadline)

    assert "CFE degraded: battery connected, MQTT connected" in caplog.text
    assert "CFE healthy:" not in caplog.text


def test_operational_heartbeat_is_unhealthy_for_stale_tcp_or_disconnected_mqtt(caplog) -> None:
    class Publisher:
        def __init__(self, connected):
            self.connected = asyncio.Event()
            if connected:
                self.connected.set()

    class Writer:
        def is_closing(self):
            return False

    stale_tcp = BatteryService(
        Settings(battery_host="battery.invalid", heartbeat_log_interval_min=1),
        Publisher(connected=True),
    )
    stale_deadline = stale_tcp._next_heartbeat_deadline
    assert stale_deadline is not None
    stale_tcp._writer = Writer()
    stale_tcp._last_rx_monotonic = stale_deadline - stale_tcp.settings.stale_after - 1
    stale_tcp._last_valid_telemetry_monotonic = stale_deadline

    mqtt_down = BatteryService(
        Settings(battery_host="battery.invalid", heartbeat_log_interval_min=1),
        Publisher(connected=False),
    )
    mqtt_deadline = mqtt_down._next_heartbeat_deadline
    assert mqtt_deadline is not None
    mqtt_down._writer = Writer()
    mqtt_down._last_rx_monotonic = mqtt_deadline
    mqtt_down._last_valid_telemetry_monotonic = mqtt_deadline

    with caplog.at_level(logging.INFO):
        stale_tcp.log_periodic_info(now=stale_deadline)
        mqtt_down.log_periodic_info(now=mqtt_deadline)

    assert "CFE unhealthy: battery stale, MQTT connected" in caplog.text
    assert "CFE unhealthy: battery connected, MQTT disconnected" in caplog.text
    assert "CFE healthy:" not in caplog.text


def test_operational_heartbeat_deadline_does_not_accumulate_execution_drift(caplog) -> None:
    class Publisher:
        connected = asyncio.Event()

        def __init__(self):
            self.connected.set()

    class Writer:
        def is_closing(self):
            return False

    service = BatteryService(
        Settings(battery_host="battery.invalid", heartbeat_log_interval_min=1),
        Publisher(),
    )
    service._writer = Writer()
    first_deadline = service._next_heartbeat_deadline
    assert first_deadline is not None
    report_at = first_deadline + 0.7
    service._last_rx_monotonic = report_at
    service._last_valid_telemetry_monotonic = report_at

    with caplog.at_level(logging.INFO):
        service.log_periodic_info(now=report_at)
        assert service._next_heartbeat_deadline == first_deadline + 60
        second_report = first_deadline + 60.2
        service._last_rx_monotonic = second_report
        service._last_valid_telemetry_monotonic = second_report
        service.log_periodic_info(now=second_report)

    assert "interval=60.7s" in caplog.text
    assert "interval=59.5s" in caplog.text
    assert service._next_heartbeat_deadline == first_deadline + 120


def test_operational_heartbeat_zero_interval_disables_log(caplog) -> None:
    class Publisher:
        connected = asyncio.Event()

    service = BatteryService(
        Settings(battery_host="battery.invalid", heartbeat_log_interval_min=0),
        Publisher(),
    )
    with caplog.at_level(logging.INFO):
        service.log_periodic_info(now=service.last_heartbeat_monotonic + 24 * 60 * 60)
    assert "CFE healthy:" not in caplog.text


def _valid_frame(length: int, *, voltage: int | None = None, soc: int | None = None) -> bytes:
    frame = bytearray(length)
    frame[0] = 0x68
    frame[-1] = 0x16
    if length == 73:
        if voltage is not None:
            frame[13:15] = voltage.to_bytes(2, "little")
        if soc is not None:
            frame[33] = soc
    elif length == 97 and voltage is not None:
        frame[19:21] = voltage.to_bytes(2, "little")
    frame[-3:-1] = crc16_modbus(frame[:-3]).to_bytes(2, "little")
    return bytes(frame)


def _varied_heartbeat() -> bytes:
    frame = bytearray(OBSERVED_INITIAL_SEQUENCE)
    frame[9] ^= 1
    frame[-3:-1] = crc16_modbus(frame[:-3]).to_bytes(2, "little")
    return bytes(frame)


def test_heartbeats_before_and_after_report_boundary_are_echoed(caplog) -> None:
    before = OBSERVED_INITIAL_SEQUENCE
    after = _varied_heartbeat()

    class Reader:
        def __init__(self, boundary):
            self.boundary = boundary
            self.before_sent = False
            self.after_sent = False
            self.cancelled_reads = 0

        async def read(self, size):
            if not self.before_sent:
                await asyncio.sleep(max(0, self.boundary - time.monotonic() - 0.01))
                self.before_sent = True
                return before
            if not self.after_sent:
                try:
                    await asyncio.sleep(max(0, self.boundary + 0.01 - time.monotonic()))
                except asyncio.CancelledError:
                    self.cancelled_reads += 1
                    raise
                self.after_sent = True
                return after
            return b""

    class Writer(FakeWriter):
        def __init__(self):
            super().__init__()
            self.writes = []

        def write(self, value):
            self.writes.append(value)

        async def drain(self):
            return None

    class Publisher:
        connected = asyncio.Event()

        def __init__(self):
            self.connected.set()

        def publish_connection(self, connected):
            pass

        def mark_stale(self, **kwargs):
            pass

        def mark_all_unavailable(self):
            pass

    async def run():
        service = BatteryService(
            Settings(battery_host="battery.invalid", stale_after=1, read_timeout=1),
            Publisher(),
        )
        service._heartbeat_interval = 0.08
        boundary = time.monotonic() + service._heartbeat_interval
        service.last_heartbeat_monotonic = boundary - service._heartbeat_interval
        service._next_heartbeat_deadline = boundary
        writer = Writer()
        reader = Reader(boundary)
        try:
            await service._session(reader, writer)
        except ConnectionError:
            pass
        return writer.writes, reader.cancelled_reads

    with caplog.at_level(logging.DEBUG):
        writes, cancelled_reads = asyncio.run(run())
    assert writes == [before, after]
    assert cancelled_reads == 0
    reports = [record.getMessage() for record in caplog.records if "CFE degraded:" in record.getMessage()]
    assert len(reports) == 1
    assert "2 heartbeats" in reports[0]
    timing = [
        record.getMessage()
        for record in caplog.records
        if "CFE health-report timing:" in record.getMessage()
    ]
    assert len(timing) == 1
    assert "session_uptime=" in timing[0]
    assert "since_tcp_rx=" in timing[0]
    assert "since_valid_cfe_frame=" in timing[0]
    assert "since_heartbeat_ack=" in timing[0]
    assert "execution=" in timing[0]
    assert "68 01 0c" not in caplog.text
    assert "Battery connection stale" not in caplog.text


def test_continuous_tcp_traffic_survives_multiple_health_reports_and_counts_exactly(caplog) -> None:
    frames = [
        OBSERVED_INITIAL_SEQUENCE,
        _valid_frame(35),
        _valid_frame(73, voltage=4968, soc=7),
        _valid_frame(97, voltage=496),
    ]

    class Reader:
        def __init__(self, service):
            self.service = service
            self.reads = 0

        async def read(self, size):
            if self.reads == 32:
                self.service.stop.set()
                return b""
            await asyncio.sleep(0.004)
            frame = frames[self.reads % len(frames)]
            self.reads += 1
            return frame

    class Writer(FakeWriter):
        def __init__(self):
            super().__init__()
            self.writes = []

        def write(self, value):
            self.writes.append(value)

        async def drain(self):
            return None

    class Publisher:
        connected = asyncio.Event()

        def __init__(self):
            self.connected.set()

        def publish_connection(self, connected):
            pass

        def mark_stale(self, **kwargs):
            pass

        def mark_all_unavailable(self):
            pass

        def publish_values(self, values):
            pass

    async def run():
        service = BatteryService(
            Settings(battery_host="battery.invalid", stale_after=1, read_timeout=1),
            Publisher(),
        )
        service._heartbeat_interval = 0.04
        service.last_heartbeat_monotonic = time.monotonic()
        service._next_heartbeat_deadline = (
            service.last_heartbeat_monotonic + service._heartbeat_interval
        )
        writer = Writer()
        observed = dict.fromkeys(service_module.FRAME_TYPES, 0)
        previous_at_report = dict.fromkeys(service_module.FRAME_TYPES, 0)
        report_counts = []
        record_frame = service._record_frame
        log_periodic_info = service.log_periodic_info

        def record(frame_type):
            record_frame(frame_type)
            observed[frame_type] += 1

        def report(now=None):
            current_time = time.monotonic() if now is None else now
            if service._next_heartbeat_deadline is not None and current_time >= service._next_heartbeat_deadline:
                actual = dict(service._interval_frame_counts)
                since_previous = {
                    key: observed[key] - previous_at_report[key] for key in observed
                }
                report_counts.append((actual, since_previous))
                previous_at_report.update(observed)
            log_periodic_info(now)

        service._record_frame = record
        service.log_periodic_info = report
        try:
            await service._session(Reader(service), writer)
        except ConnectionError:
            pass
        return observed, report_counts, writer.writes

    with caplog.at_level(logging.INFO):
        observed, report_counts, writes = asyncio.run(run())
    assert len(report_counts) >= 2
    assert all(actual == expected for actual, expected in report_counts)
    assert observed == {"HEARTBEAT": 8, "STATUS": 8, "SUMMARY": 8, "DETAIL": 8}
    assert writes == [OBSERVED_INITIAL_SEQUENCE] * 8
    assert "Battery connection stale" not in caplog.text
    assert caplog.text.count("CFE healthy:") + caplog.text.count("CFE degraded:") == len(report_counts)


def test_continuous_tcp_traffic_with_reporting_disabled_keeps_acknowledging(caplog) -> None:
    class Reader:
        def __init__(self, service):
            self.service = service
            self.reads = 0

        async def read(self, size):
            if self.reads == 20:
                self.service.stop.set()
                return b""
            await asyncio.sleep(0.004)
            self.reads += 1
            return _varied_heartbeat()

    class Writer(FakeWriter):
        def __init__(self):
            super().__init__()
            self.writes = []

        def write(self, value):
            self.writes.append(value)

        async def drain(self):
            return None

    class Publisher:
        def __init__(self):
            self.connected = asyncio.Event()
            self.connected.set()

        def publish_connection(self, connected):
            pass

        def mark_stale(self, **kwargs):
            pass

        def mark_all_unavailable(self):
            pass

    async def run():
        service = BatteryService(
            Settings(
                battery_host="battery.invalid",
                stale_after=1,
                read_timeout=1,
                heartbeat_log_interval_min=0,
            ),
            Publisher(),
        )
        writer = Writer()
        try:
            await service._session(Reader(service), writer)
        except ConnectionError:
            pass
        return writer.writes, service._next_heartbeat_deadline

    with caplog.at_level(logging.INFO):
        writes, deadline = asyncio.run(run())
    assert writes == [_varied_heartbeat()] * 20
    assert deadline is None
    assert "CFE healthy:" not in caplog.text
    assert "CFE degraded:" not in caplog.text
    assert "Battery connection stale" not in caplog.text


def test_frame_counters_are_crc_valid_per_session_and_per_report(caplog) -> None:
    class Reader:
        def __init__(self, data):
            self.chunks = [data, b""]

        async def read(self, size):
            return self.chunks.pop(0)

    class Writer(FakeWriter):
        def is_closing(self):
            return self.closed

        def write(self, data):
            pass

        async def drain(self):
            pass

    class Publisher:
        def __init__(self):
            self.connected = asyncio.Event()
            self.connected.set()

        def publish_connection(self, connected):
            pass

        def mark_stale(self, **kwargs):
            pass

        def mark_all_unavailable(self):
            pass

        def publish_values(self, values):
            pass

    async def run():
        service = BatteryService(Settings(battery_host="battery.invalid"), Publisher())
        snapshots = []
        session_number = 1
        record_frame = service._record_frame

        def record(frame_type):
            record_frame(frame_type)
            snapshots.append(
                (session_number, frame_type, dict(service._session_frame_counts), dict(service._interval_frame_counts))
            )

        service._record_frame = record

        corrupt_summary = bytearray(_valid_frame(73, voltage=4968, soc=7))
        corrupt_summary[-2] ^= 1
        first_data = (
            OBSERVED_INITIAL_SEQUENCE * 2
            + _valid_frame(35)
            + bytes(corrupt_summary)
            + _valid_frame(73, voltage=4968, soc=7)
            + _valid_frame(97, voltage=495)
        )
        try:
            await service._session(Reader(first_data), Writer())
        except ConnectionError:
            pass
        first_session_counts = dict(service._session_frame_counts)
        first_interval_counts = dict(service._interval_frame_counts)

        session_number = 2
        service._on_connection_established()
        try:
            await service._session(
                Reader(_valid_frame(35) + _valid_frame(73, voltage=4970, soc=8)),
                Writer(),
            )
        except ConnectionError:
            pass
        return service, snapshots, first_session_counts, first_interval_counts

    service, snapshots, first_session_counts, first_interval_counts = asyncio.run(run())
    first_last = [item for item in snapshots if item[0] == 1][-1]
    second_last = [item for item in snapshots if item[0] == 2][-1]
    assert first_last[2] == {"HEARTBEAT": 2, "STATUS": 1, "SUMMARY": 1, "DETAIL": 1}
    assert first_last[3] == first_last[2]
    assert second_last[2] == {"HEARTBEAT": 0, "STATUS": 1, "SUMMARY": 1, "DETAIL": 0}
    assert second_last[3] == second_last[2]
    assert first_session_counts == dict.fromkeys(service_module.FRAME_TYPES, 0)
    assert first_interval_counts == dict.fromkeys(service_module.FRAME_TYPES, 0)
    assert service._session_frame_counts == dict.fromkeys(service_module.FRAME_TYPES, 0)
    assert service._interval_frame_counts == dict.fromkeys(service_module.FRAME_TYPES, 0)
    assert service._latest_soc == 8
    assert service._latest_voltage == 49.7
    report_at = service._next_heartbeat_deadline
    assert report_at is not None
    with caplog.at_level(logging.INFO):
        service.log_periodic_info(now=report_at)
    assert "SOC=8%, voltage=49.70V" in caplog.text


def test_silent_tcp_session_reconnects_and_resets_counts(caplog) -> None:
    class SilentReader:
        async def read(self, size):
            await asyncio.Future()

    class EofReader:
        async def read(self, size):
            return b""

    class Writer(FakeWriter):
        def is_closing(self):
            return self.closed

    class Publisher:
        def __init__(self):
            self.connected = asyncio.Event()
            self.connection_down = asyncio.Event()

        def publish_connection(self, connected):
            if not connected:
                self.connection_down.set()

        def mark_stale(self, **kwargs):
            pass

        def mark_all_unavailable(self):
            pass

    async def run():
        publisher = Publisher()
        service = BatteryService(
            Settings(battery_host="battery.invalid", stale_after=0.03, read_timeout=1), publisher
        )
        attempts = 0

        async def connect():
            nonlocal attempts
            attempts += 1
            return (SilentReader() if attempts == 1 else EofReader()), Writer()

        async def session(reader, writer):
            try:
                await service._session(reader, writer)
            except ConnectionError:
                if attempts >= 2:
                    service.stop.set()
                raise

        with caplog.at_level(logging.DEBUG):
            await reconnect_loop(
                connect,
                session,
                stop=service.stop,
                retry_delay=0.001,
                on_connected=service._on_connection_established,
            )
        return attempts, service, publisher

    attempts, service, publisher = asyncio.run(run())
    assert attempts == 2
    assert publisher.connection_down.is_set()
    assert "Battery connection stale: no TCP data received" in caplog.text
    assert "CFE stale TCP session timing:" in caplog.text
    assert "since_valid_cfe_frame=N/A" in caplog.text
    assert "since_heartbeat_ack=N/A" in caplog.text
    assert service._session_frame_counts == dict.fromkeys(service_module.FRAME_TYPES, 0)
    assert service._interval_frame_counts == dict.fromkeys(service_module.FRAME_TYPES, 0)


def test_valid_heartbeat_traffic_keeps_tcp_session_without_fresh_telemetry(caplog) -> None:
    class Reader:
        def __init__(self, service):
            self.service = service
            self.count = 0

        async def read(self, size):
            await asyncio.sleep(0.01)
            self.count += 1
            if self.count == 7:
                self.service.stop.set()
            return OBSERVED_INITIAL_SEQUENCE

    class Writer(FakeWriter):
        def is_closing(self):
            return self.closed

        def write(self, data):
            pass

        async def drain(self):
            pass

    class Publisher:
        connected = asyncio.Event()

        def __init__(self):
            self.connected.set()

        def publish_connection(self, connected):
            pass

        def mark_stale(self, **kwargs):
            pass

        def mark_all_unavailable(self):
            pass

    async def run():
        service = BatteryService(
            Settings(battery_host="battery.invalid", stale_after=0.03, read_timeout=1), Publisher()
        )
        attempts = 0

        async def connect():
            nonlocal attempts
            attempts += 1
            return Reader(service), Writer()

        with caplog.at_level(logging.WARNING):
            await reconnect_loop(
                connect,
                service._session,
                stop=service.stop,
                retry_delay=0.001,
                on_connected=service._on_connection_established,
            )
        return attempts

    assert asyncio.run(run()) == 1
    assert "Battery telemetry stale" in caplog.text
    assert "Battery connection stale" not in caplog.text


def test_shutdown_during_stale_recovery_does_not_reconnect() -> None:
    class SilentReader:
        async def read(self, size):
            await asyncio.Future()

    class Writer(FakeWriter):
        def is_closing(self):
            return self.closed

    class Publisher:
        def __init__(self):
            self.connected = asyncio.Event()
            self.connection_down = asyncio.Event()

        def publish_connection(self, connected):
            if not connected:
                self.connection_down.set()

        def mark_stale(self, **kwargs):
            pass

        def mark_all_unavailable(self):
            pass

    async def run():
        publisher = Publisher()
        service = BatteryService(
            Settings(battery_host="battery.invalid", stale_after=0.02, read_timeout=1), publisher
        )
        attempts = 0

        async def connect():
            nonlocal attempts
            attempts += 1
            writer = Writer()
            service._writer = writer
            return SilentReader(), writer

        session_task = asyncio.create_task(
            reconnect_loop(
                connect,
                service._session,
                stop=service.stop,
                retry_delay=1,
                on_connected=service._on_connection_established,
            )
        )
        await asyncio.wait_for(publisher.connection_down.wait(), timeout=1)
        service.request_shutdown("SIGTERM")
        await asyncio.wait_for(session_task, timeout=1)
        return attempts, service

    attempts, service = asyncio.run(run())
    assert attempts == 1
    assert service.stop.is_set()
    assert service._session_frame_counts == dict.fromkeys(service_module.FRAME_TYPES, 0)
