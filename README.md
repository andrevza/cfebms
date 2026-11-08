# cfebms

![CFE BMS battery monitoring](docs/images/cfebms-banner.png)

`cfebms` is a read-only TCP-to-MQTT service for monitoring CFE lithium battery
systems. The currently supported target is the **CFE-5100S**; compatibility
with other CFE models has not been established. It publishes decoded battery
telemetry and Home Assistant MQTT discovery entities.

The service recognizes 19-, 35-, 73-, and 97-byte CFE frames, validates
CRC-16/MODBUS, handles fragmented and concatenated TCP reads, and echoes only
the recognized 19-byte heartbeat. It reconnects after connection loss,
reports stale data, and shuts down cleanly. SOC, SOH, pack measurements,
capacity and energy totals, cell measurements, limits, temperatures, and
operating state are published where the reference decoder defines them. SOC
is read from SUMMARY frames. No battery configuration, firmware, or control
commands are sent.

Telemetry field mappings were ported from the working CFE-5100S decoder used
during development. Sanitized telemetry captures are not included, so the
automated protocol tests use synthetic frames; see
[`docs/PROTOCOL.md`](docs/PROTOCOL.md) and
[`docs/PROTOCOL_RESEARCH.md`](docs/PROTOCOL_RESEARCH.md) for mappings and
verification limits. Remaining evidence gaps are listed in
[`docs/OPEN_QUESTIONS.md`](docs/OPEN_QUESTIONS.md).

## Home Assistant App

Add `https://github.com/andrevza/cfebms` under **Settings → Apps → App store →
⋮ → Repositories**, install **CFE BMS**, and configure the battery endpoint and
MQTT broker in the App configuration. The App package targets `aarch64` and
`amd64`. The repository must be available on GitHub for Supervisor to install
it; installation in a live Supervisor instance has not yet been verified.
Configure Home Assistant's MQTT integration for the same broker and keep MQTT
discovery enabled.
See [`DOCS.md`](DOCS.md) for setup, configuration, upgrade, logging, and
troubleshooting details.

## Standalone Docker Compose

Copy the sample environment file, set reachable battery and MQTT addresses,
then start the service:

```sh
cp .env.example .env
# Edit .env and set CFE_BATTERY_HOST and MQTT_HOST (and broker credentials if required).
docker compose up --build -d cfebms
docker compose logs -f cfebms
```

The example uses reserved placeholder hostnames; replace them with addresses
reachable from the Docker bridge network. The service does not require
privileged mode or host networking. Do not run the standalone container and
the Home Assistant App at the same time; they share an MQTT device identity.

## Development

Development, tests, and the diagnostic CLI run in Docker; no Python packages
need to be installed on the host. Run the offline test suite with:

```sh
docker compose run --build --rm test
```

Build and use the diagnostic CLI with a frame or a local capture file:

```sh
docker build -t cfebms .
docker run --rm cfebms decode --hex "68 01 0c 00 01 b0 84 57 01 0a 01 00 00 00 00 04 00 c3 16"
docker run --rm -v "$PWD/captures:/captures:ro" cfebms decode --file /captures/capture.bin --file-format raw
```

Review [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the current module
boundaries and [`docs/PROTOCOL.md`](docs/PROTOCOL.md) for implemented framing
and decoding behavior. Development guidance is in [`AGENTS.md`](AGENTS.md).

## License

Copyright (C) 2026 Andre van der Walt.

`cfebms` is licensed under the GNU General Public License v3.0 only
(`GPL-3.0-only`). See the complete terms in [`LICENSE`](LICENSE).
