# bmspace reference analysis

Reference: the sibling checkout at `../bmspace/`; if it is unavailable, use
[andrevza/bmspace](https://github.com/andrevza/bmspace). The local checkout was
inspected on 8 November 2026, including `bms.py`,
`constants.py`, runtime config, Docker, Compose and Home Assistant App files.
bmspace is a Pace BMS project. Its protocol implementation is not applicable
to CFE and remains separate.

## Observed project structure and features

The local checkout is a procedural Python application centered on `bms.py`,
with shared Pace command constants, model variants, YAML/App configuration,
Docker files and Home Assistant App metadata (`config.yaml`, `run.sh`,
`repository.yaml`). The runtime owns connection state, frame buffering,
protocol requests/decoding, MQTT publishing and polling. The README describes
cells, temperatures, SOC/SOH, warnings, state and balancing telemetry.

The docs describe configuration for MQTT host/port/credentials, connection
type, BMS endpoint or serial path, scan interval, retry behavior, parser
options, topic naming, discovery and logging. IP and serial are selectable
connection modes. This is a useful configuration pattern, but cfebms should
start with TCP because only TCP port 6868 is currently observed.

## Requested comparison areas

| Area | Reference finding | cfebms takeaway |
|---|---|---|
| Application architecture | `bms.py` is the procedural runtime for transport, Pace requests, parsing, MQTT and polling; constants and model-specific copies sit beside it | Keep CFE parsing separate; reuse only generic operational conventions |
| Configuration / connection | YAML options or Home Assistant `/data/options.json`; supports IP/serial mode, broker credentials, scan interval, retries, parser settings and topic prefixes | cfebms uses environment config for Docker and TCP only |
| TCP / serial transport | Transport branches live in the runtime. TCP reads use a persistent buffer and `recv(4096)`; Pace framing uses its own `0x7e`/CR delimiters. Serial uses line reads | cfebms uses async TCP, observed CFE lengths and CRC; Pace framing is not reused |
| Polling / message processing | Runtime sends Pace command requests for pack count, analog, capacity, version, serial and warnings, then polls at `scan_interval` | CFE command semantics are unknown, so cfebms remains receive-only |
| MQTT topics | Paho; configurable base topic; root `/availability`; pack paths include `pack_N/v_pack`, `i_pack`, `soc`, `soh`, `v_cells/cell_N`, and `temps/temp_N` | cfebms aligns supported measurements to pack-oriented topic names under its own prefix |
| Home Assistant discovery | Retained per-component configs under `<prefix>/<component>/BMS-<serial>/<name>/config`, with stable IDs derived from device serial | cfebms uses the same topic shape and stable IDs based on the known model because no CFE serial field is documented |
| Docker | Alpine/Python 3.9 image. Local Compose requests `privileged: true` and mounts `/dev` for serial support | cfebms has a separate non-root runtime image and ordinary bridge networking |
| Home Assistant App | Root-level App metadata, option schema and launcher are present | cfebms Compose is the current deployment path |
| Errors / diagnostics / logs | Synchronous connect/retry loops, print-based diagnostics, return-code/checksum validation, and reconnect handling are in the runtime | cfebms uses structured Python logging, async reconnect and timeouts, with CFE validation kept separate |
| Operational heartbeat | The current local `bms.py` has no `heartbeat_log_interval_min`, `log_periodic_info`, `last_heartbeat_monotonic`, or `Heartbeat: app alive` implementation. Its main loop is paced by `scan_interval`, and discovery is periodically requested after an elapsed scan-count threshold | cfebms's `HEARTBEAT_LOG_INTERVAL_MIN` operational report follows the requested behavior directly; it is a cfebms-specific facility, not a port of code found in this checkout. It reports TCP/MQTT status and interval CFE counters using monotonic time |
| Tests / CI | No `tests/` directory exists in this local checkout; `.github/workflows/stale.yml` only handles stale issues/PRs | cfebms tests MQTT/discovery and service behavior with offline fakes |

## Reuse and licensing

The reference repository identifies GPL-3.0 licensing. This initial project
contains no copied bmspace source code. Architectural concepts such as
configuration validation, retry controls, topic-prefix configuration,
discovery adapters and container packaging are general design patterns.
If code is reused later, record its provenance, retain applicable copyright and
license notices, and comply with GPL-3.0 distribution obligations. The new
project's own license remains to be selected.

## cfebms integration alignment

The cfebms MQTT layer follows the reusable bmspace conventions without copying
its GPL-3.0 source: configurable root topic, `pack_1/...` metric paths,
`BMS-<device>` discovery topic grouping, stable unique IDs, retained discovery
config, Home Assistant birth handling, and a shared `/availability` topic.
The TCP reconnect loop is continuous rather than the reference's finite
connection retry policy. No Pace request bytes, frame parser, field offsets,
serial-number extraction, or identity rules were carried over.

## Current operational review

The local reference is a synchronous `bms.py` application. It manages TCP or
serial transport and MQTT callbacks with module-level connection flags, uses
`scan_interval` to pace BMS polling, and provides a synchronous signal/exit
cleanup path. Its `debug_output` numeric option gates lower-level receive and
frame diagnostics. The `docker-compose.yaml` service grants privileged access
and mounts `/dev` because the same application supports serial BMS devices.

cfebms uses an asyncio TCP reconnect loop, structured logging controlled by
`LOG_LEVEL`, a Paho MQTT network loop, bounded asynchronous shutdown, and an
unprivileged bridge-network container. Those differences address its TCP-only
CFE transport and are intentionally retained. cfebms also waits for queued
offline availability publications before MQTT disconnect; the local bmspace
shutdown publishes availability but does not wait for delivery confirmation.

The current local bmspace checkout does not implement the named operational
heartbeat API. Therefore, cfebms's `HEARTBEAT_LOG_INTERVAL_MIN` setting and
monotonic health report are cfebms-specific. There is one periodic operational
health report; the older duplicate telemetry summary was removed.
