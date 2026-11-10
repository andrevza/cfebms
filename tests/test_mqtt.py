from __future__ import annotations

import asyncio
import json
import logging

from cfebms.config import Settings
from cfebms.mqtt import (
    ENTITY_SPECS,
    MQTTPublisher,
    discovery_payload,
    discovery_topic,
)


class PublishResult:
    rc = 0

    def is_published(self):
        return True


class ReasonCode:
    def __init__(self, *, is_failure: bool) -> None:
        self.is_failure = is_failure

    def __str__(self) -> str:
        return "Not authorized" if self.is_failure else "Success"


class FakeMQTTClient:
    def __init__(self) -> None:
        self.published: list[tuple[str, str, int, bool]] = []
        self.will = None
        self.username = None
        self.on_connect = None
        self.on_disconnect = None
        self.on_message = None
        self.subscriptions = []
        self.events = []

    def will_set(self, topic, payload, qos=0, retain=False):
        self.will = (topic, payload, qos, retain)

    def username_pw_set(self, username, password):
        self.username = (username, password)

    def publish(self, topic, payload, qos=0, retain=False):
        self.published.append((topic, payload, qos, retain))
        self.events.append(("publish", topic, payload))
        return PublishResult()

    def subscribe(self, topic, qos=0):
        self.subscriptions.append((topic, qos))

    def disconnect(self):
        self.events.append(("disconnect",))

    def loop_stop(self):
        self.events.append(("loop_stop",))


def settings(**overrides) -> Settings:
    values = {"battery_host": "battery.invalid"}
    values.update(overrides)
    return Settings(**values)


def test_battery_rtc_diagnostics_do_not_add_home_assistant_entities() -> None:
    expected_ids = {
        "pack_1_v_pack",
        "pack_1_i_pack",
        "pack_1_soc",
        "pack_1_soh",
        "pack_1_state",
        "pack_1_power",
        "pack_1_charge_energy",
        "pack_1_discharge_energy",
        "pack_1_charge_capacity",
        "pack_1_discharge_capacity",
        "pack_1_v_cell_min",
        "pack_1_v_cell_max",
        "pack_1_v_cell_avg",
        "pack_1_cells_max_diff",
        "pack_1_cell_min_index",
        "pack_1_cell_max_index",
        *(f"pack_1_v_cell_{index}" for index in range(1, 17)),
        *(f"pack_1_temp_{index}" for index in range(1, 4)),
        "pack_1_temp_min",
        "pack_1_temp_max",
        "pack_1_charge_voltage_limit",
        "pack_1_charge_current_limit",
        "pack_1_discharge_voltage_limit",
        "pack_1_discharge_current_limit",
        "battery_connection",
    }
    assert {spec.object_id for spec in ENTITY_SPECS} == expected_ids
    assert len(expected_ids) == 42


def test_discovery_payload_has_stable_device_metadata() -> None:
    spec = next(item for item in ENTITY_SPECS if item.object_id == "pack_1_v_pack")
    payload = discovery_payload(spec, settings())
    assert payload["unique_id"] == "cfebms_cfe5100s_pack_1_v_pack"
    assert payload["unit_of_measurement"] == "V"
    assert payload["device_class"] == "voltage"
    assert payload["suggested_display_precision"] == 2
    assert payload["state_class"] == "measurement"
    assert payload["device"]["identifiers"] == ["cfebms_cfe5100s"]
    assert payload["device"]["name"] == "CFE Battery"
    assert payload["device"]["manufacturer"] == "CFE"
    assert payload["device"]["model"] == "CFE-5100S"
    assert "sw_version" not in payload["device"]
    assert payload["state_topic"] == "cfebms/pack_1/v_pack"
    assert payload["availability"][0]["topic"] == "cfebms/availability"
    assert payload["availability"][1]["topic"] == "cfebms/availability/pack_1_v_pack"
    assert payload["availability_mode"] == "all"
    assert discovery_topic("homeassistant", spec) == (
        "homeassistant/sensor/BMS-CFE-5100S/pack_1_v_pack/config"
    )


def test_discovery_payload_uses_normal_sensor_name() -> None:
    spec = next(item for item in ENTITY_SPECS if item.object_id == "pack_1_i_pack")
    payload = discovery_payload(spec, settings())
    assert payload["name"] == "Pack 1 Current"


def test_publisher_will_measurements_and_stale_availability() -> None:
    client = FakeMQTTClient()
    publisher = MQTTPublisher(settings(), client=client)
    assert client.will == ("cfebms/availability", "offline", 1, True)
    publisher.publish_values({"voltage_v": 52.3}, now=100.0)
    publisher.mark_stale(stale_after=30.0, now=131.0)
    assert ("cfebms/pack_1/v_pack", "52.30", 1, True) in client.published
    assert (
        "cfebms/availability/pack_1_v_pack", "offline", 1, True
    ) in client.published


def test_publisher_marks_all_sampled_entities_unavailable_on_disconnect() -> None:
    client = FakeMQTTClient()
    publisher = MQTTPublisher(settings(), client=client)
    publisher.publish_values({"voltage_v": 51.0, "current_a": -1.0}, now=10.0)
    publisher.mark_all_unavailable()
    assert ("cfebms/availability/pack_1_v_pack", "offline", 1, True) in client.published
    assert ("cfebms/availability/pack_1_i_pack", "offline", 1, True) in client.published
    assert publisher._last_seen == {}


def test_publisher_routes_decoded_summary_and_detail_values() -> None:
    client = FakeMQTTClient()
    publisher = MQTTPublisher(settings(), client=client)
    publisher.publish_values({
        "soc_percent": 84,
        "cell_16_v": 3.412,
        "cell_average_v": 3.401,
        "temperature_2_c": 27,
        "charge_voltage_limit_v": 56.0,
    })
    emitted = {(topic, payload) for topic, payload, *_ in client.published}
    assert ("cfebms/pack_1/soc", "84") in emitted
    assert ("cfebms/pack_1/v_cells/cell_16", "3412") in emitted
    assert ("cfebms/pack_1/v_cell_avg", "3401.0") in emitted
    assert ("cfebms/pack_1/temps/temp_2", "27") in emitted
    assert ("cfebms/pack_1/charge_voltage_limit", "56.0") in emitted


def test_cell_voltage_payloads_convert_volts_to_millivolts_without_mutating_input() -> None:
    client = FakeMQTTClient()
    publisher = MQTTPublisher(settings(), client=client)
    values = {
        "cell_1_v": 3.132,
        "cell_min_v": 3.121,
        "cell_max_v": 3.422,
        "cell_average_v": 3.2715,
        "cell_delta_mv": 301,
    }

    publisher.publish_values(values)
    emitted = {(topic, payload) for topic, payload, *_ in client.published}

    assert ("cfebms/pack_1/v_cells/cell_1", "3132") in emitted
    assert ("cfebms/pack_1/v_cell_min", "3121") in emitted
    assert ("cfebms/pack_1/v_cell_max", "3422") in emitted
    assert ("cfebms/pack_1/v_cell_avg", "3271.5") in emitted
    assert ("cfebms/pack_1/cells_max_diff_calc", "301") in emitted
    assert values["cell_1_v"] == 3.132


def test_discovery_precision_units_classes_and_identifiers_are_stable() -> None:
    precision_by_id = {
        "pack_1_v_pack": 2,
        "pack_1_i_pack": 2,
        "pack_1_power": 2,
        "pack_1_soc": 0,
        "pack_1_soh": 0,
        "pack_1_charge_energy": 2,
        "pack_1_charge_capacity": 2,
        "pack_1_temp_1": 1,
        "pack_1_charge_voltage_limit": 2,
    }
    specs = {spec.object_id: spec for spec in ENTITY_SPECS}
    for object_id, precision in precision_by_id.items():
        payload = discovery_payload(specs[object_id], settings())
        assert payload["suggested_display_precision"] == precision

    for object_id in (
        "pack_1_v_cell_1",
        "pack_1_v_cell_min",
        "pack_1_v_cell_max",
        "pack_1_v_cell_avg",
    ):
        spec = specs[object_id]
        payload = discovery_payload(spec, settings())
        assert payload["unit_of_measurement"] == "mV"
        assert payload["device_class"] == "voltage"
        assert payload["unique_id"] == f"cfebms_cfe5100s_{object_id}"
        assert discovery_topic("homeassistant", spec).endswith(f"/{object_id}/config")

    assert discovery_payload(specs["pack_1_charge_energy"], settings())["state_class"] == "total_increasing"
    assert discovery_payload(specs["pack_1_discharge_energy"], settings())["device_class"] == "energy"
    assert discovery_payload(specs["pack_1_charge_capacity"], settings())["state_class"] == "total_increasing"


def test_technical_entities_are_discovery_diagnostics() -> None:
    specs = {spec.object_id: spec for spec in ENTITY_SPECS}
    expected_diagnostics = {
        "pack_1_charge_voltage_limit",
        "pack_1_discharge_voltage_limit",
        "pack_1_charge_current_limit",
        "pack_1_discharge_current_limit",
        "pack_1_charge_capacity",
        "pack_1_discharge_capacity",
        "pack_1_cell_max_index",
        "pack_1_cell_min_index",
        "battery_connection",
    }
    for object_id in expected_diagnostics:
        assert discovery_payload(specs[object_id], settings())["entity_category"] == "diagnostic"

    normal_sensors = {
        "pack_1_soc",
        "pack_1_soh",
        "pack_1_v_pack",
        "pack_1_i_pack",
        "pack_1_power",
        "pack_1_charge_energy",
        "pack_1_discharge_energy",
        "pack_1_v_cell_1",
        "pack_1_temp_1",
    }
    for object_id in normal_sensors:
        assert "entity_category" not in discovery_payload(specs[object_id], settings())


def test_pack_voltage_payload_and_discovery_preserve_two_decimal_volts() -> None:
    client = FakeMQTTClient()
    publisher = MQTTPublisher(settings(), client=client)
    publisher.publish_values({"voltage_v": 49.6})

    voltage_spec = next(spec for spec in ENTITY_SPECS if spec.object_id == "pack_1_v_pack")
    config = discovery_payload(voltage_spec, settings())
    assert ("cfebms/pack_1/v_pack", "49.60", 1, True) in client.published
    assert config["unit_of_measurement"] == "V"
    assert config["device_class"] == "voltage"
    assert config["suggested_display_precision"] == 2
    assert config["unique_id"] == "cfebms_cfe5100s_pack_1_v_pack"
    assert config["state_topic"] == "cfebms/pack_1/v_pack"


def test_discovery_updates_existing_topics_retained_in_place() -> None:
    client = FakeMQTTClient()
    publisher = MQTTPublisher(settings(), client=client)
    publisher.publish_discovery()
    publisher.publish_discovery()

    configs = [item for item in client.published if item[0].endswith("/config")]
    topic = "homeassistant/sensor/BMS-CFE-5100S/pack_1_v_cell_1/config"
    updates = [json.loads(payload) for current_topic, payload, _, retained in configs if current_topic == topic and retained]
    assert len(updates) == 2
    assert updates[0]["unique_id"] == updates[1]["unique_id"] == "cfebms_cfe5100s_pack_1_v_cell_1"
    assert updates[1]["unit_of_measurement"] == "mV"
    assert len({current_topic for current_topic, *_ in configs}) == len(ENTITY_SPECS)


def test_discovery_publishes_only_currently_decoded_measurements() -> None:
    client = FakeMQTTClient()
    publisher = MQTTPublisher(settings(), client=client)
    publisher.publish_discovery()
    topics = {topic for topic, *_ in client.published}
    assert "homeassistant/sensor/BMS-CFE-5100S/pack_1_v_pack/config" in topics
    discovery_topics = {topic for topic in topics if topic.endswith("/config")}
    assert len(discovery_topics) == len(ENTITY_SPECS)


def test_mqtt_connect_sets_availability_and_subscribes_for_birth(caplog) -> None:
    client = FakeMQTTClient()
    publisher = MQTTPublisher(settings(), client=client)
    with caplog.at_level(logging.INFO):
        publisher._on_connect(client, None, None, ReasonCode(is_failure=False), None)
        publisher._on_connect(client, None, None, ReasonCode(is_failure=False), None)
    assert ("homeassistant/status", 1) in client.subscriptions
    assert len(client.subscriptions) == 2
    assert (
        "cfebms/availability", "online", 1, True
    ) in client.published
    assert "MQTT connected to broker" in caplog.text
    assert "MQTT reconnected to broker" in caplog.text


def test_mqtt_connect_rejects_failed_reason_code() -> None:
    client = FakeMQTTClient()
    publisher = MQTTPublisher(settings(), client=client)
    publisher._on_connect(client, None, None, ReasonCode(is_failure=True), None)
    assert client.subscriptions == []
    assert client.published == []


def test_mqtt_publish_failure_logs_topic(caplog) -> None:
    class FailedResult:
        rc = 4

    class FailedClient(FakeMQTTClient):
        def publish(self, topic, payload, qos=0, retain=False):
            return FailedResult()

    publisher = MQTTPublisher(settings(), client=FailedClient())
    with caplog.at_level(logging.WARNING):
        assert publisher._publish("cfebms/pack_1/v_pack", "50.0") is False
    assert "MQTT publish failed for cfebms/pack_1/v_pack" in caplog.text


def test_mqtt_connect_error_includes_exception_type_and_fallback(caplog) -> None:
    class EmptySocketError(OSError):
        def __str__(self):
            return ""

    class FailedConnectClient(FakeMQTTClient):
        def __init__(self, stop):
            super().__init__()
            self.stop = stop

        def connect(self, host, port, keepalive):
            self.stop.set()
            raise EmptySocketError()

    async def run():
        stop = asyncio.Event()
        publisher = MQTTPublisher(settings(), client=FailedConnectClient(stop))
        await publisher.start(stop=stop, retry_delay=0.001)

    with caplog.at_level(logging.INFO):
        asyncio.run(run())
    assert "Connecting to MQTT broker at" in caplog.text
    assert "MQTT connection failed: EmptySocketError: no additional details" in caplog.text


def test_home_assistant_birth_republishes_retained_discovery() -> None:
    client = FakeMQTTClient()
    publisher = MQTTPublisher(settings(), client=client)

    class Message:
        topic = "homeassistant/status"
        payload = b"online"

    publisher._on_message(client, None, Message())
    assert any(topic == "homeassistant/sensor/BMS-CFE-5100S/pack_1_v_pack/config" for topic, *_ in client.published)


def test_graceful_shutdown_publishes_offline_before_disconnect_and_is_idempotent() -> None:
    async def run():
        client = FakeMQTTClient()
        publisher = MQTTPublisher(settings(), client=client)
        publisher.publish_values({"voltage_v": 52.3, "current_a": -1.2})
        await publisher.graceful_shutdown()
        first_count = len(client.published)
        await publisher.graceful_shutdown()
        return client, first_count

    client, first_count = asyncio.run(run())
    events = client.events
    assert ("cfebms/connection", "offline", 1, True) in client.published
    assert ("cfebms/availability", "offline", 1, True) in client.published
    assert ("cfebms/availability/pack_1_v_pack", "offline", 1, True) in client.published
    assert ("cfebms/availability/pack_1_i_pack", "offline", 1, True) in client.published
    assert events[-2:] == [("disconnect",), ("loop_stop",)]
    assert events.index(("publish", "cfebms/availability", "offline")) < events.index(("disconnect",))
    assert len(client.published) == first_count


def test_graceful_shutdown_publication_timeout_still_cleans_up(caplog) -> None:
    class PendingResult:
        rc = 0

        def is_published(self):
            return False

    class PendingClient(FakeMQTTClient):
        def publish(self, topic, payload, qos=0, retain=False):
            self.published.append((topic, payload, qos, retain))
            self.events.append(("publish", topic, payload))
            return PendingResult()

    async def run():
        client = PendingClient()
        publisher = MQTTPublisher(settings(), client=client)
        await publisher.graceful_shutdown(timeout=0.02)
        return client

    with caplog.at_level(logging.WARNING):
        client = asyncio.run(run())
    assert "Timed out waiting for MQTT offline availability publications" in caplog.text
    assert client.events[-2:] == [("disconnect",), ("loop_stop",)]


def test_expected_mqtt_disconnect_is_not_logged_as_warning(caplog) -> None:
    async def run():
        client = FakeMQTTClient()
        publisher = MQTTPublisher(settings(), client=client)
        publisher._shutdown_started = True
        publisher._on_disconnect(client, None, None, None, None)

    with caplog.at_level(logging.WARNING):
        asyncio.run(run())
    assert "MQTT disconnected" not in caplog.text


def test_offline_publish_failure_during_shutdown_is_not_warning(caplog) -> None:
    class DisconnectedClient(FakeMQTTClient):
        def publish(self, topic, payload, qos=0, retain=False):
            class FailedResult:
                rc = 4

            return FailedResult()

    async def run():
        publisher = MQTTPublisher(settings(), client=DisconnectedClient())
        await publisher.graceful_shutdown(timeout=0.01)

    with caplog.at_level(logging.WARNING):
        asyncio.run(run())
    assert "MQTT publish failed" not in caplog.text
