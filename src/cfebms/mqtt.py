"""MQTT telemetry and Home Assistant MQTT discovery publishing."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass
from typing import Any

import paho.mqtt.client as mqtt

from .config import Settings

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class EntitySpec:
    object_id: str
    name: str
    state_path: str
    unit: str | None = None
    device_class: str | None = None
    state_class: str | None = None
    component: str = "sensor"
    display_precision: int | None = None
    entity_category: str | None = None


ENTITY_SPECS: tuple[EntitySpec, ...] = (
    EntitySpec("pack_1_v_pack", "Pack 1 Voltage", "pack_1/v_pack", "V", "voltage", "measurement", display_precision=2),
    EntitySpec("pack_1_i_pack", "Pack 1 Current", "pack_1/i_pack", "A", "current", "measurement", display_precision=2),
    EntitySpec("pack_1_soc", "Pack 1 State of Charge", "pack_1/soc", "%", "battery", "measurement", display_precision=0),
    EntitySpec("pack_1_soh", "Pack 1 State of Health", "pack_1/soh", "%", None, "measurement", display_precision=0),
    EntitySpec("pack_1_state", "Pack 1 Charge State", "pack_1/state"),
    EntitySpec("pack_1_power", "Pack 1 Power", "pack_1/power", "W", "power", "measurement", display_precision=2),
    EntitySpec("pack_1_charge_energy", "Pack 1 Charge Energy", "pack_1/charge_energy", "kWh", "energy", "total_increasing", display_precision=2),
    EntitySpec("pack_1_discharge_energy", "Pack 1 Discharge Energy", "pack_1/discharge_energy", "kWh", "energy", "total_increasing", display_precision=2),
    EntitySpec("pack_1_charge_capacity", "Pack 1 Charge Capacity", "pack_1/i_charge_cap", "Ah", None, "total_increasing", display_precision=2, entity_category="diagnostic"),
    EntitySpec("pack_1_discharge_capacity", "Pack 1 Discharge Capacity", "pack_1/i_discharge_cap", "Ah", None, "total_increasing", display_precision=2, entity_category="diagnostic"),
    EntitySpec("pack_1_v_cell_min", "Pack 1 Minimum Cell Voltage", "pack_1/v_cell_min", "mV", "voltage", "measurement", display_precision=0),
    EntitySpec("pack_1_v_cell_max", "Pack 1 Maximum Cell Voltage", "pack_1/v_cell_max", "mV", "voltage", "measurement", display_precision=0),
    EntitySpec("pack_1_v_cell_avg", "Pack 1 Average Cell Voltage", "pack_1/v_cell_avg", "mV", "voltage", "measurement", display_precision=1),
    EntitySpec("pack_1_cells_max_diff", "Pack 1 Cell Max Volt Diff", "pack_1/cells_max_diff_calc", "mV", None, "measurement", display_precision=0),
    EntitySpec("pack_1_cell_min_index", "Pack 1 Minimum Cell Index", "pack_1/cell_min_index", entity_category="diagnostic"),
    EntitySpec("pack_1_cell_max_index", "Pack 1 Maximum Cell Index", "pack_1/cell_max_index", entity_category="diagnostic"),
    *(EntitySpec(f"pack_1_v_cell_{index}", f"Pack 1 Cell {index} Voltage", f"pack_1/v_cells/cell_{index}", "mV", "voltage", "measurement", display_precision=0) for index in range(1, 17)),
    *(EntitySpec(f"pack_1_temp_{index}", f"Pack 1 Temperature {index}", f"pack_1/temps/temp_{index}", "°C", "temperature", "measurement", display_precision=1) for index in range(1, 4)),
    EntitySpec("pack_1_temp_min", "Pack 1 Minimum Temperature", "pack_1/temps/temp_min", "°C", "temperature", "measurement", display_precision=1),
    EntitySpec("pack_1_temp_max", "Pack 1 Maximum Temperature", "pack_1/temps/temp_max", "°C", "temperature", "measurement", display_precision=1),
    EntitySpec("pack_1_charge_voltage_limit", "Pack 1 Charge Voltage Limit", "pack_1/charge_voltage_limit", "V", "voltage", "measurement", display_precision=2, entity_category="diagnostic"),
    EntitySpec("pack_1_charge_current_limit", "Pack 1 Charge Current Limit", "pack_1/charge_current_limit", "A", "current", "measurement", display_precision=2, entity_category="diagnostic"),
    EntitySpec("pack_1_discharge_voltage_limit", "Pack 1 Discharge Voltage Limit", "pack_1/discharge_voltage_limit", "V", "voltage", "measurement", display_precision=2, entity_category="diagnostic"),
    EntitySpec("pack_1_discharge_current_limit", "Pack 1 Discharge Current Limit", "pack_1/discharge_current_limit", "A", "current", "measurement", display_precision=2, entity_category="diagnostic"),
    EntitySpec("battery_connection", "Battery Connection", "connection", component="binary_sensor", entity_category="diagnostic"),
)


VALUE_TO_ENTITY = {
    "voltage_v": "pack_1_v_pack",
    "current_a": "pack_1_i_pack",
    "soc_percent": "pack_1_soc",
    "soh_percent": "pack_1_soh",
    "operating_state": "pack_1_state",
    "power_w": "pack_1_power",
    "charge_energy_kwh": "pack_1_charge_energy",
    "discharge_energy_kwh": "pack_1_discharge_energy",
    "discharge_capacity_ah": "pack_1_discharge_capacity",
    "charge_capacity_ah": "pack_1_charge_capacity",
    "cell_min_v": "pack_1_v_cell_min",
    "cell_max_v": "pack_1_v_cell_max",
    "cell_delta_mv": "pack_1_cells_max_diff",
    "cell_average_v": "pack_1_v_cell_avg",
    "cell_min_index": "pack_1_cell_min_index",
    "cell_max_index": "pack_1_cell_max_index",
    **{f"cell_{index}_v": f"pack_1_v_cell_{index}" for index in range(1, 17)},
    **{f"temperature_{index}_c": f"pack_1_temp_{index}" for index in range(1, 4)},
    "temperature_min_c": "pack_1_temp_min",
    "temperature_max_c": "pack_1_temp_max",
    "charge_voltage_limit_v": "pack_1_charge_voltage_limit",
    "charge_current_limit_a": "pack_1_charge_current_limit",
    "discharge_voltage_limit_v": "pack_1_discharge_voltage_limit",
    "discharge_current_limit_a": "pack_1_discharge_current_limit",
}

ENTITY_BY_ID = {spec.object_id: spec for spec in ENTITY_SPECS}
CELL_VOLTAGE_VALUE_KEYS = {
    "cell_min_v",
    "cell_max_v",
    "cell_average_v",
    *(f"cell_{index}_v" for index in range(1, 17)),
}


def discovery_topic(prefix: str, spec: EntitySpec) -> str:
    return f"{prefix}/{spec.component}/BMS-CFE-5100S/{spec.object_id}/config"


def discovery_payload(spec: EntitySpec, settings: Settings) -> dict[str, Any]:
    state_topic = f"{settings.base_topic}/{spec.state_path}"
    availability = [{
        "topic": f"{settings.base_topic}/availability",
        "payload_available": "online",
        "payload_not_available": "offline",
    }]
    if spec.component != "binary_sensor":
        availability.append({
            "topic": f"{settings.base_topic}/availability/{spec.object_id}",
            "payload_available": "online",
            "payload_not_available": "offline",
        })
    payload: dict[str, Any] = {
        "name": spec.name,
        "unique_id": f"cfebms_cfe5100s_{spec.object_id}",
        "object_id": spec.object_id,
        "state_topic": state_topic,
        "availability": availability,
        "availability_mode": "all",
        "device": {
            "identifiers": ["cfebms_cfe5100s"],
            "name": "CFE Battery",
            "manufacturer": "CFE",
            "model": "CFE-5100S",
        },
    }
    if spec.unit:
        payload["unit_of_measurement"] = spec.unit
    if spec.device_class:
        payload["device_class"] = spec.device_class
    if spec.state_class:
        payload["state_class"] = spec.state_class
    if spec.display_precision is not None:
        payload["suggested_display_precision"] = spec.display_precision
    if spec.entity_category:
        payload["entity_category"] = spec.entity_category
    if spec.component == "binary_sensor":
        payload.update(payload_on="online", payload_off="offline", device_class="connectivity")
    return payload


class MQTTPublisher:
    """Paho-backed retained publisher with MQTT discovery and per-sensor freshness."""

    def __init__(self, settings: Settings, *, client: Any | None = None) -> None:
        self.settings = settings
        self.client = client or mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id="cfebms-cfe5100s",
        )
        self.connected = asyncio.Event()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._last_seen: dict[str, float] = {}
        self._battery_connected = False
        self._ever_connected = False
        self._has_published_telemetry = False
        self._publish_failure_logged = False
        self._shutdown_started = False
        self._shutdown_complete = False
        self._shutdown_done = asyncio.Event()
        self._shutdown_publications: list[Any] = []
        self.client.will_set(f"{settings.base_topic}/availability", "offline", qos=1, retain=True)
        if settings.mqtt_username:
            self.client.username_pw_set(settings.mqtt_username, settings.mqtt_password)
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._on_message

    def _on_connect(self, client: Any, userdata: Any, flags: Any, reason_code: Any, properties: Any) -> None:
        if self._shutdown_started:
            return
        if reason_code.is_failure:
            _LOGGER.error("MQTT connection rejected: %s", reason_code)
            return
        if self._ever_connected:
            _LOGGER.info("MQTT reconnected to broker %s:%d", self.settings.mqtt_host, self.settings.mqtt_port)
        else:
            _LOGGER.info("MQTT connected to broker %s:%d", self.settings.mqtt_host, self.settings.mqtt_port)
        self._ever_connected = True
        if self._loop:
            self._loop.call_soon_threadsafe(self.connected.set)
        client.subscribe(f"{self.settings.discovery_prefix}/status", qos=1)
        self.publish_connection(self._battery_connected)
        self._publish(f"{self.settings.base_topic}/availability", "online", retain=True)

    def _on_message(self, client: Any, userdata: Any, message: Any) -> None:
        if message.topic == f"{self.settings.discovery_prefix}/status":
            if message.payload == b"online":
                _LOGGER.info("Home Assistant MQTT birth received; republishing discovery")
                self.publish_discovery()
            return

    def _on_disconnect(self, client: Any, userdata: Any, disconnect_flags: Any, reason_code: Any, properties: Any) -> None:
        if self._loop:
            self._loop.call_soon_threadsafe(self.connected.clear)
        disconnect_reason = str(reason_code).strip() if reason_code is not None else ""
        disconnect_reason = disconnect_reason or "no reason supplied"
        if self._shutdown_started:
            _LOGGER.info("MQTT disconnected gracefully")
        else:
            _LOGGER.warning("MQTT disconnected from broker: %s", disconnect_reason)

    def _publish(self, topic: str, payload: str, *, retain: bool = True) -> bool:
        try:
            result = self.client.publish(topic, payload, qos=1, retain=retain)
        except Exception as exc:
            detail = str(exc).strip() or "no additional details"
            if self._shutdown_started:
                _LOGGER.debug("MQTT shutdown publish unavailable for %s: %s: %s", topic, type(exc).__name__, detail)
            elif not self._publish_failure_logged:
                _LOGGER.warning("MQTT publish failed for %s: %s: %s", topic, type(exc).__name__, detail)
                self._publish_failure_logged = True
            else:
                _LOGGER.debug("Additional MQTT publish failure for %s: %s: %s", topic, type(exc).__name__, detail)
            return False
        rc = getattr(result, "rc", 0)
        if rc != mqtt.MQTT_ERR_SUCCESS:
            detail = mqtt.error_string(rc) or "no additional details"
            if self._shutdown_started:
                _LOGGER.debug("MQTT shutdown publish unavailable for %s (rc=%s): %s", topic, rc, detail)
            elif not self._publish_failure_logged:
                _LOGGER.warning("MQTT publish failed for %s (rc=%s): %s", topic, rc, detail)
                self._publish_failure_logged = True
            else:
                _LOGGER.debug("Additional MQTT publish failure for %s (rc=%s): %s", topic, rc, detail)
            return False
        self._publish_failure_logged = False
        if self._shutdown_started and not self._shutdown_complete:
            self._shutdown_publications.append(result)
        return True

    async def start(
        self,
        *,
        retry_delay: float = 5.0,
        stop: asyncio.Event | None = None,
    ) -> None:
        self._loop = asyncio.get_running_loop()
        if self.settings.mqtt_username:
            self.client.username_pw_set(self.settings.mqtt_username, self.settings.mqtt_password)
        attempt = 0
        while stop is None or not stop.is_set():
            attempt += 1
            try:
                _LOGGER.info(
                    "Connecting to MQTT broker at %s:%d (attempt %d)",
                    self.settings.mqtt_host,
                    self.settings.mqtt_port,
                    attempt,
                )
                await asyncio.to_thread(
                    self.client.connect,
                    self.settings.mqtt_host,
                    self.settings.mqtt_port,
                    60,
                )
                self.client.loop_start()
                await asyncio.wait_for(self.connected.wait(), timeout=10.0)
                self.publish_discovery()
                return
            except (OSError, TimeoutError, asyncio.TimeoutError) as exc:
                detail = str(exc).strip() or "no additional details"
                _LOGGER.error("MQTT connection failed: %s: %s", type(exc).__name__, detail)
                try:
                    self.client.loop_stop()
                except Exception:
                    pass
                if stop is None:
                    await asyncio.sleep(retry_delay)
                else:
                    try:
                        await asyncio.wait_for(stop.wait(), timeout=retry_delay)
                    except asyncio.TimeoutError:
                        pass

    def publish_discovery(self) -> None:
        _LOGGER.info("Publishing Home Assistant discovery for %d entities", len(ENTITY_SPECS))
        for spec in ENTITY_SPECS:
            self._publish(
                discovery_topic(self.settings.discovery_prefix, spec),
                json.dumps(discovery_payload(spec, self.settings), separators=(",", ":")),
            )
            if spec.component == "sensor":
                self._publish(
                    f"{self.settings.base_topic}/availability/{spec.object_id}",
                    "offline",
                )

    def publish_connection(self, connected: bool) -> None:
        self._battery_connected = connected
        self._publish(
            f"{self.settings.base_topic}/connection",
            "online" if connected else "offline",
        )

    def publish_values(self, values: dict[str, int | float | str], *, now: float | None = None) -> None:
        now = time.monotonic() if now is None else now
        for key, value in values.items():
            object_id = VALUE_TO_ENTITY.get(key)
            if object_id is None:
                _LOGGER.warning("Not publishing unsupported telemetry key %s", key)
                continue
            spec = ENTITY_BY_ID[object_id]
            payload = str(value)
            if key == "voltage_v":
                payload = f"{float(value):.2f}"
            elif key in CELL_VOLTAGE_VALUE_KEYS:
                precision = spec.display_precision or 0
                payload = f"{float(value) * 1000:.{precision}f}"
            published = self._publish(f"{self.settings.base_topic}/{spec.state_path}", payload)
            self._publish(f"{self.settings.base_topic}/availability/{object_id}", "online")
            self._last_seen[object_id] = now
            if published and not self._has_published_telemetry:
                _LOGGER.info("First battery telemetry published to MQTT (%d measurement(s))", len(values))
                self._has_published_telemetry = True

    def mark_stale(self, *, stale_after: float, now: float | None = None) -> None:
        now = time.monotonic() if now is None else now
        for object_id, last_seen in tuple(self._last_seen.items()):
            if now - last_seen > stale_after:
                self._publish(f"{self.settings.base_topic}/availability/{object_id}", "offline")
                del self._last_seen[object_id]

    def mark_all_unavailable(self) -> None:
        for object_id in tuple(self._last_seen):
            self._publish(f"{self.settings.base_topic}/availability/{object_id}", "offline")
        self._last_seen.clear()

    async def graceful_shutdown(self, *, timeout: float = 5.0) -> None:
        """Publish offline state, drain it briefly, then stop Paho cleanly."""
        if self._shutdown_started:
            await self._shutdown_done.wait()
            return
        self._shutdown_started = True
        try:
            _LOGGER.info("Publishing MQTT offline availability")
            self.publish_connection(False)
            self._publish(f"{self.settings.base_topic}/availability", "offline")
            for spec in ENTITY_SPECS:
                if spec.component != "sensor":
                    continue
                self._publish(
                    f"{self.settings.base_topic}/availability/{spec.object_id}",
                    "offline",
                )
            self._last_seen.clear()

            deadline = asyncio.get_running_loop().time() + timeout
            if self._shutdown_publications:
                while not all(self._publication_complete(item) for item in self._shutdown_publications):
                    if asyncio.get_running_loop().time() >= deadline:
                        _LOGGER.warning("Timed out waiting for MQTT offline availability publications")
                        break
                    await asyncio.sleep(0.02)
                else:
                    _LOGGER.info("MQTT offline availability published and delivery completed")
            else:
                _LOGGER.info("MQTT offline availability could not be queued; broker is unavailable")

            await self._run_cleanup_call("disconnect", timeout=2.0)
            await self._run_cleanup_call("loop_stop", timeout=2.0)
            _LOGGER.info("Graceful shutdown complete")
        finally:
            self._shutdown_complete = True
            self._shutdown_done.set()

    @staticmethod
    def _publication_complete(publication: Any) -> bool:
        try:
            return bool(publication.is_published())
        except (AttributeError, RuntimeError):
            # Test doubles and older clients without message tracking are treated as queued.
            return True

    async def _run_cleanup_call(self, method_name: str, *, timeout: float) -> None:
        method = getattr(self.client, method_name, None)
        if method is None:
            return
        try:
            await asyncio.wait_for(asyncio.to_thread(method), timeout=timeout)
        except asyncio.TimeoutError:
            _LOGGER.warning("Timed out during MQTT %s", method_name)
        except Exception as exc:
            _LOGGER.info("MQTT %s cleanup detail: %s: %s", method_name, type(exc).__name__, str(exc).strip() or "no additional details")
