# Architecture

`cfebms` is a read-only CFE TCP client and MQTT publisher. Its runtime path is:

```text
service.py: TCP connect, read, close, reconnect, and session lifecycle
        ↓
frames.py: incremental framing, CRC validation, and resynchronization
        ↓
protocol.py: CFE frame classification and supported field decoding
        ↓
models.py: decoded telemetry values and raw unsupported bytes
        ↓
service.py: heartbeat echo, freshness, availability, and health orchestration
        ↓
mqtt.py: state publication, availability, and Home Assistant discovery
```

`config.py` validates environment-based settings. `supervisor.py` maps Home
Assistant App options into the same runtime configuration; `cli.py` provides
the service and offline frame-decoding entry points. TCP connection handling
currently lives in `service.py`; there is no separate transport abstraction.
The package can be tested without a live battery, broker, or Home Assistant
installation.

## Runtime behavior

The service connects to the configured CFE endpoint (TCP port 6868 by default)
and processes a continuous stream. TCP read boundaries are not treated as
frame boundaries. The frame assembler accepts the four observed frame lengths,
checks CRC-16/MODBUS, emits valid frames, and resynchronizes after invalid
input. `models.py` carries decoded telemetry values and raw unsupported bytes.
Only the recognized CRC-valid 19-byte heartbeat is echoed; the service sends
no other battery commands.

The decoder returns measurements supported by the ported CFE reference
implementation. Unsupported or unknown data is not published as a valid
measurement. The service tracks battery and telemetry freshness separately:
TCP silence ends the session and enters reconnect handling, while active TCP
traffic with stale measurements is reported as degraded and readings become
unavailable according to the configured stale interval.

MQTT publishing uses the stable `cfebms` device and topic conventions, retained
Home Assistant discovery configuration, broker Last Will, and battery sensor
availability. Graceful shutdown stops battery input and heartbeat replies,
publishes offline availability, waits for bounded delivery, then disconnects
MQTT. It does not remove discovery configuration.

## Configuration and packaging

Runtime configuration is provided through environment variables. The
Home Assistant App adapter reads Supervisor options and maps them into those
same variables. Docker Compose supports standalone deployment; the production
image runs without privileged mode or host networking. See
[`../DOCS.md`](../DOCS.md) for deployment instructions.

## Testing

The test suite uses deterministic synthetic frames and fake TCP/MQTT peers.
No sanitized telemetry capture fixtures are currently checked in, so tests
exercise the decoder port and stream handling but do not independently
validate telemetry fields against a capture from hardware. See
[`PROTOCOL.md`](PROTOCOL.md) and [`OPEN_QUESTIONS.md`](OPEN_QUESTIONS.md).
