"""Read-only TCP receiver with bounded reconnect and stale-data handling."""

from __future__ import annotations

import asyncio
import logging
import signal
import time
from collections.abc import Awaitable, Callable
from typing import Any

from .config import Settings
from .frames import FrameAssembler, cfe_frame_length
from .mqtt import MQTTPublisher
from .protocol import decode_cfe_telemetry

_LOGGER = logging.getLogger(__name__)
FRAME_TYPES = ("HEARTBEAT", "STATUS", "SUMMARY", "DETAIL")


def _exception_details(exc: BaseException) -> str:
    detail = str(exc).strip() or "no additional details"
    return f"{type(exc).__name__}: {detail}"


async def reconnect_loop(
    connect: Callable[[], Awaitable[tuple[Any, Any]]],
    session: Callable[[Any, Any], Awaitable[None]],
    *,
    stop: asyncio.Event,
    retry_delay: float,
    on_connected: Callable[[], None] | None = None,
    on_periodic_info: Callable[[], None] | None = None,
) -> None:
    """Retry connections until stopped; exposed for deterministic fake tests."""
    consecutive_failures = 0
    while not stop.is_set():
        if on_periodic_info is not None:
            on_periodic_info()
        writer: Any | None = None
        try:
            reader, writer = await connect()
            consecutive_failures = 0
            if on_connected is not None:
                on_connected()
            if stop.is_set():
                return
            await session(reader, writer)
        except asyncio.CancelledError:
            raise
        except (OSError, TimeoutError, asyncio.TimeoutError, ConnectionError) as exc:
            if stop.is_set():
                _LOGGER.debug("Battery session ended during shutdown: %s", _exception_details(exc))
            else:
                consecutive_failures += 1
                details = _exception_details(exc)
                if isinstance(exc, (ConnectionRefusedError, TimeoutError, asyncio.TimeoutError)):
                    failure = f"Battery TCP connection failed: {details}"
                elif isinstance(exc, ConnectionError):
                    failure = f"Battery TCP connection lost or closed: {details}"
                else:
                    failure = f"Battery TCP connection failed: {details}"
                _LOGGER.warning(
                    "%s (consecutive failures: %d). Retrying in %s seconds.",
                    failure,
                    consecutive_failures,
                    f"{retry_delay:g}",
                )
        except Exception as exc:
            if stop.is_set():
                _LOGGER.debug("Battery session ended during shutdown: %s", _exception_details(exc))
            else:
                consecutive_failures += 1
                _LOGGER.exception("Unexpected battery session failure: %s", _exception_details(exc))
                _LOGGER.warning(
                    "Battery connection failed (consecutive failures: %d). Retrying in %s seconds.",
                    consecutive_failures,
                    f"{retry_delay:g}",
                )
        finally:
            if writer is not None:
                try:
                    writer.close()
                except Exception as exc:
                    _LOGGER.warning("Error closing CFE TCP connection: %s", _exception_details(exc))
                wait_closed = getattr(writer, "wait_closed", None)
                if wait_closed:
                    try:
                        await asyncio.wait_for(wait_closed(), timeout=2.0)
                    except asyncio.TimeoutError:
                        _LOGGER.warning("Timed out waiting for CFE TCP connection to close")
                    except (OSError, RuntimeError) as exc:
                        if not stop.is_set():
                            _LOGGER.debug("CFE TCP close detail: %s", _exception_details(exc))
        if not stop.is_set():
            retry_deadline = asyncio.get_running_loop().time() + retry_delay
            while not stop.is_set():
                if on_periodic_info is not None:
                    on_periodic_info()
                wait_seconds = retry_deadline - asyncio.get_running_loop().time()
                if wait_seconds <= 0:
                    break
                try:
                    await asyncio.wait_for(stop.wait(), timeout=wait_seconds)
                except asyncio.TimeoutError:
                    continue


class BatteryService:
    def __init__(self, settings: Settings, publisher: MQTTPublisher) -> None:
        self.settings = settings
        self.publisher = publisher
        self.stop = asyncio.Event()
        self._writer: asyncio.StreamWriter | None = None
        self._shutdown_disconnect_logged = False
        self.last_heartbeat_monotonic = time.monotonic()
        self._heartbeat_interval = settings.heartbeat_log_interval_min * 60.0
        self._next_heartbeat_deadline = (
            self.last_heartbeat_monotonic + self._heartbeat_interval
            if self._heartbeat_interval
            else None
        )
        self._session_frame_counts = dict.fromkeys(FRAME_TYPES, 0)
        self._interval_frame_counts = dict.fromkeys(FRAME_TYPES, 0)
        self._last_rx_monotonic: float | None = None
        self._session_started_monotonic: float | None = None
        self._last_valid_frame_monotonic: float | None = None
        self._last_heartbeat_ack_monotonic: float | None = None
        self._last_valid_telemetry_monotonic: float | None = None
        self._latest_soc: int | float | None = None
        self._latest_voltage: int | float | None = None
        self._latest_battery_rtc: str | None = None

    def request_shutdown(self, reason: str) -> None:
        if self.stop.is_set():
            return
        _LOGGER.info("Shutdown requested (%s)", reason)
        self.stop.set()
        if self._writer is not None:
            try:
                self._writer.close()
            except Exception as exc:
                _LOGGER.warning("Error closing CFE battery connection: %s", _exception_details(exc))

    def handle_signal(self, signum: int) -> None:
        try:
            reason = signal.Signals(signum).name
        except ValueError:
            reason = f"signal {signum}"
        self.request_shutdown(reason)

    def log_shutdown_disconnect_if_needed(self) -> None:
        _LOGGER.info("Battery communication stopped")
        if not self._shutdown_disconnect_logged:
            _LOGGER.info("CFE battery disconnected")
            self._shutdown_disconnect_logged = True

    async def run(self) -> None:
        async def connect() -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
            _LOGGER.info(
                "Connecting to battery at %s:%d",
                self.settings.battery_host,
                self.settings.battery_port,
            )
            return await asyncio.wait_for(
                asyncio.open_connection(self.settings.battery_host, self.settings.battery_port),
                timeout=self.settings.connect_timeout,
            )

        await reconnect_loop(
            connect,
            self._session,
            stop=self.stop,
            retry_delay=self.settings.reconnect_delay,
            on_connected=self._on_connection_established,
            on_periodic_info=self.log_periodic_info,
        )

    def _reset_operational_counters(self, now: float | None = None) -> None:
        now = time.monotonic() if now is None else now
        self._session_frame_counts = dict.fromkeys(FRAME_TYPES, 0)
        self._interval_frame_counts = dict.fromkeys(FRAME_TYPES, 0)
        self.last_heartbeat_monotonic = now
        self._next_heartbeat_deadline = (
            now + self._heartbeat_interval if self._heartbeat_interval else None
        )

    def _record_frame(self, frame_type: str) -> None:
        """Count one complete CRC-valid frame emitted by the frame assembler."""
        if frame_type in self._session_frame_counts:
            self._session_frame_counts[frame_type] += 1
            self._interval_frame_counts[frame_type] += 1

    def _on_connection_established(self) -> None:
        self._reset_operational_counters()
        _LOGGER.info(
            "Connected to CFE battery %s:%d (failure counter reset)",
            self.settings.battery_host,
            self.settings.battery_port,
        )

    def _log_session_timing(self, event: str, *, execution_ms: float | None = None) -> None:
        now = time.monotonic()

        def since(timestamp: float | None) -> str:
            if timestamp is None:
                return "N/A"
            return f"{max(0.0, now - timestamp):.3f}s"

        session_uptime = (
            "N/A"
            if self._session_started_monotonic is None
            else f"{now - self._session_started_monotonic:.3f}s"
        )
        duration = "N/A" if execution_ms is None else f"{execution_ms:.3f}ms"
        _LOGGER.debug(
            "CFE %s timing: session_uptime=%s, since_tcp_rx=%s, "
            "since_valid_cfe_frame=%s, since_heartbeat_ack=%s, execution=%s",
            event,
            session_uptime,
            since(self._last_rx_monotonic),
            since(self._last_valid_frame_monotonic),
            since(self._last_heartbeat_ack_monotonic),
            duration,
        )

    def _connection_health(self, now: float) -> tuple[str, str]:
        is_closing = getattr(self._writer, "is_closing", lambda: False)
        battery_connected = self._writer is not None and not is_closing()
        tcp_stale = (
            battery_connected
            and self._last_rx_monotonic is not None
            and now - self._last_rx_monotonic >= self.settings.stale_after
        )
        mqtt_connected = self.publisher.connected.is_set()
        telemetry_fresh = (
            self._last_valid_telemetry_monotonic is not None
            and now - self._last_valid_telemetry_monotonic < self.settings.stale_after
        )
        if not battery_connected or tcp_stale or not mqtt_connected:
            overall = "unhealthy"
        elif not telemetry_fresh:
            overall = "degraded"
        else:
            overall = "healthy"
        battery_status = (
            "disconnected" if not battery_connected else "stale" if tcp_stale else "connected"
        )
        mqtt_status = "connected" if mqtt_connected else "disconnected"
        return overall, f"battery {battery_status}, MQTT {mqtt_status}"

    def log_periodic_info(self, now: float | None = None) -> None:
        if self._next_heartbeat_deadline is None:
            return
        now = time.monotonic() if now is None else now
        if now < self._next_heartbeat_deadline:
            return

        report_started = time.monotonic()
        elapsed = now - self.last_heartbeat_monotonic
        overall, connection_status = self._connection_health(now)
        soc = "N/A" if self._latest_soc is None else f"{float(self._latest_soc):g}%"
        voltage = "N/A" if self._latest_voltage is None else f"{float(self._latest_voltage):.2f}V"
        battery_rtc = self._latest_battery_rtc or "N/A"
        counts = self._interval_frame_counts
        _LOGGER.info(
            "CFE %s: %s, %d heartbeats, %d statuses, %d summaries, %d detail frames, "
            "SOC=%s, voltage=%s, battery_rtc=%s (interval=%.1fs)",
            overall,
            connection_status,
            counts["HEARTBEAT"],
            counts["STATUS"],
            counts["SUMMARY"],
            counts["DETAIL"],
            soc,
            voltage,
            battery_rtc,
            elapsed,
        )
        self.last_heartbeat_monotonic = now
        # Advance from the previous deadline so late wakeups do not accumulate
        # into a progressively later reporting schedule.
        missed_intervals = max(
            1, int((now - self._next_heartbeat_deadline) // self._heartbeat_interval) + 1
        )
        self._next_heartbeat_deadline += missed_intervals * self._heartbeat_interval
        self._interval_frame_counts = dict.fromkeys(FRAME_TYPES, 0)
        report_finished = time.monotonic()
        self._log_session_timing(
            "health-report", execution_ms=(report_finished - report_started) * 1000
        )

    async def _session(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        _LOGGER.debug("CFE battery TCP session active")
        self._writer = writer
        self._session_frame_counts = dict.fromkeys(FRAME_TYPES, 0)
        session_started = time.monotonic()
        self._session_started_monotonic = session_started
        self._last_valid_frame_monotonic = None
        self._last_heartbeat_ack_monotonic = None
        last_rx = session_started
        last_telemetry = self._last_valid_telemetry_monotonic or session_started
        self._last_rx_monotonic = last_rx
        self.publisher.publish_connection(True)
        telemetry_stale = False
        assembler = FrameAssembler(cfe_frame_length, max_buffer_size=65536)
        first_frame_types: set[str] = set()
        try:
            while not self.stop.is_set():
                now = time.monotonic()
                self.log_periodic_info(now)
                tcp_remaining = self.settings.stale_after - (now - last_rx)
                if tcp_remaining <= 0:
                    self.publisher.mark_stale(stale_after=self.settings.stale_after, now=now)
                    self._log_session_timing("stale TCP session")
                    _LOGGER.warning(
                        "Battery connection stale: no TCP data received for %.1f seconds",
                        now - last_rx,
                    )
                    self.publisher.publish_connection(False)
                    raise ConnectionError(
                        f"no TCP bytes received for {now - last_rx:.1f} seconds"
                    )

                read_timeout = min(self.settings.read_timeout, tcp_remaining)
                telemetry_remaining = self.settings.stale_after - (now - last_telemetry)
                if not telemetry_stale:
                    if telemetry_remaining <= 0:
                        _LOGGER.warning(
                            "Battery telemetry stale: no decoded measurements for %.1f seconds",
                            now - last_telemetry,
                        )
                        telemetry_stale = True
                    else:
                        read_timeout = min(read_timeout, telemetry_remaining)
                try:
                    chunk = await asyncio.wait_for(reader.read(4096), timeout=read_timeout)
                except asyncio.TimeoutError:
                    now = time.monotonic()
                    self.publisher.mark_stale(stale_after=self.settings.stale_after, now=now)
                    if not telemetry_stale and now - last_telemetry >= self.settings.stale_after:
                        _LOGGER.warning(
                            "Battery telemetry stale: no decoded measurements for %.1f seconds",
                            now - last_telemetry,
                        )
                        telemetry_stale = True
                    if now - last_rx >= self.settings.stale_after:
                        self._log_session_timing("stale TCP session")
                        _LOGGER.warning(
                            "Battery connection stale: no TCP data received for %.1f seconds",
                            now - last_rx,
                        )
                        self.publisher.publish_connection(False)
                        raise ConnectionError(
                            f"no TCP bytes received for {now - last_rx:.1f} seconds"
                        )
                    continue
                if not chunk:
                    raise ConnectionError("battery closed the TCP stream")
                last_rx = time.monotonic()
                self._last_rx_monotonic = last_rx
                self.publisher.mark_stale(stale_after=self.settings.stale_after, now=last_rx)
                if not telemetry_stale and last_rx - last_telemetry >= self.settings.stale_after:
                    _LOGGER.warning(
                        "Battery telemetry stale: no decoded measurements for %.1f seconds",
                        last_rx - last_telemetry,
                    )
                    telemetry_stale = True
                frames = assembler.feed(chunk)
                for diagnostic in assembler.diagnostics:
                    _LOGGER.debug("CFE frame parser detail: %s: %s", diagnostic.code, diagnostic.detail)
                if assembler.diagnostics:
                    _LOGGER.warning(
                        "CFE framing/CRC error: discarded %d malformed byte(s) while resynchronizing",
                        len(assembler.diagnostics),
                    )
                for frame in frames:
                    if self.stop.is_set():
                        break
                    self._last_valid_frame_monotonic = time.monotonic()
                    frame_type = {
                        19: "HEARTBEAT",
                        35: "STATUS",
                        73: "SUMMARY",
                        97: "DETAIL",
                    }.get(len(frame), "UNKNOWN")
                    self._record_frame(frame_type)
                    if frame_type == "HEARTBEAT":
                        heartbeat_count = self._session_frame_counts["HEARTBEAT"]
                        if heartbeat_count == 1:
                            _LOGGER.info("First CRC-valid CFE heartbeat received")
                        _LOGGER.debug("CFE heartbeat #%d received (length=%d)", heartbeat_count, len(frame))
                        writer.write(frame)
                        await writer.drain()
                        self._last_heartbeat_ack_monotonic = time.monotonic()
                        if heartbeat_count == 1:
                            _LOGGER.info("First CFE heartbeat acknowledged")
                        _LOGGER.debug("CFE heartbeat #%d acknowledged", heartbeat_count)
                        continue
                    if frame_type in {"STATUS", "SUMMARY", "DETAIL"}:
                        if frame_type not in first_frame_types:
                            _LOGGER.info("First valid CFE %s frame received (length=%d)", frame_type, len(frame))
                            first_frame_types.add(frame_type)
                    _LOGGER.debug("RX CFE %s frame length=%d", frame_type, len(frame))
                    telemetry = decode_cfe_telemetry(frame)
                    rtc = telemetry.diagnostics.get("battery_rtc_iso")
                    if isinstance(rtc, str) and rtc:
                        self._latest_battery_rtc = rtc
                    for warning in telemetry.warnings:
                        _LOGGER.warning("CFE %s decode warning (length=%d): %s", frame_type, len(frame), warning or "no details")
                        _LOGGER.debug("CFE parse failure frame length=%d", len(frame))
                    if telemetry.values:
                        if "soc_percent" in telemetry.values:
                            self._latest_soc = telemetry.values["soc_percent"]
                        if "voltage_v" in telemetry.values:
                            self._latest_voltage = telemetry.values["voltage_v"]
                        now = time.monotonic()
                        self._last_valid_telemetry_monotonic = now
                        last_telemetry = now
                        if telemetry_stale:
                            _LOGGER.info("Battery telemetry recovered after stale interval")
                            telemetry_stale = False
                        _LOGGER.debug("Decoded CFE %s measurements: %s", frame_type, telemetry.values)
                        self.publisher.publish_values(telemetry.values)
        finally:
            try:
                writer.close()
                wait_closed = getattr(writer, "wait_closed", None)
                if wait_closed:
                    await asyncio.wait_for(wait_closed(), timeout=2.0)
                _LOGGER.info("CFE battery TCP connection closed")
            except asyncio.TimeoutError:
                _LOGGER.warning("Timed out waiting for CFE battery connection to close")
            except (OSError, RuntimeError) as exc:
                if not self.stop.is_set():
                    _LOGGER.debug("CFE TCP close detail: %s", _exception_details(exc))
            self._writer = None
            self._last_rx_monotonic = None
            self._session_started_monotonic = None
            self._last_valid_frame_monotonic = None
            self._last_heartbeat_ack_monotonic = None
            self._reset_operational_counters()
            _LOGGER.info("CFE battery disconnected")
            if self.stop.is_set():
                self._shutdown_disconnect_logged = True
            if not self.stop.is_set():
                self.publisher.publish_connection(False)
                self.publisher.mark_all_unavailable()


async def run_service(settings: Settings) -> None:
    publisher = MQTTPublisher(settings)
    service = BatteryService(settings, publisher)
    loop = asyncio.get_running_loop()
    signals = (signal.SIGINT, signal.SIGTERM)
    for sig in signals:
        try:
            loop.add_signal_handler(sig, service.handle_signal, sig)
        except (NotImplementedError, RuntimeError):
            pass
    service_task: asyncio.Task[None] | None = None
    stop_task: asyncio.Task[bool] | None = None
    try:
        await publisher.start(retry_delay=settings.reconnect_delay, stop=service.stop)
        if service.stop.is_set():
            return
        service_task = asyncio.create_task(service.run())
        stop_task = asyncio.create_task(service.stop.wait())
        done, _ = await asyncio.wait(
            (service_task, stop_task), return_when=asyncio.FIRST_COMPLETED
        )
        if stop_task in done and not service_task.done():
            service_task.cancel()
        try:
            await service_task
        except asyncio.CancelledError:
            if not service.stop.is_set():
                raise
    finally:
        if not service.stop.is_set():
            service.request_shutdown("service exit")
        if service_task is not None and not service_task.done():
            service_task.cancel()
            try:
                await service_task
            except asyncio.CancelledError:
                pass
        service.log_shutdown_disconnect_if_needed()
        if stop_task is not None and not stop_task.done():
            stop_task.cancel()
        await publisher.graceful_shutdown()
        for sig in signals:
            try:
                loop.remove_signal_handler(sig)
            except (NotImplementedError, RuntimeError):
                pass
