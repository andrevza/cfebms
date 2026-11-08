# cfebms

![CFE BMS battery monitoring](https://raw.githubusercontent.com/andrevza/cfebms/main/docs/images/cfebms-banner.png)

CFE BMS brings battery data from supported CFE lithium batteries into Home
Assistant. It currently supports the **CFE-5100S**.

- Monitors the battery over TCP in read-only mode.
- Publishes telemetry to MQTT and adds sensors to Home Assistant through
  automatic MQTT discovery.
- Reports SOC, SOH, pack voltage and current, individual cell voltages,
  temperatures, and operating status.
- Reconnects automatically after communication interruptions.

Configure Home Assistant's MQTT integration to use the same broker and keep
MQTT discovery enabled.

## Documentation

- [Installation, configuration, and troubleshooting](https://github.com/andrevza/cfebms/blob/main/DOCS.md)
- [Implemented protocol behavior](https://github.com/andrevza/cfebms/blob/main/docs/PROTOCOL.md)
- [Decoder mappings and verification limits](https://github.com/andrevza/cfebms/blob/main/docs/PROTOCOL_RESEARCH.md)
- [Open protocol questions](https://github.com/andrevza/cfebms/blob/main/docs/OPEN_QUESTIONS.md)

## Home Assistant App

Add `https://github.com/andrevza/cfebms` under **Settings → Apps → App store →
⋮ → Repositories**, install **CFE BMS**, and configure the battery endpoint and
MQTT broker in the App configuration. The App package targets `aarch64` and
`amd64`. The repository must be available on GitHub for Supervisor to install
it; installation in a live Supervisor instance has not yet been verified.

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
docker run --rm --entrypoint /run.sh cfebms decode --hex "68 01 0c 00 01 b0 84 57 01 0a 01 00 00 00 00 04 00 c3 16"
docker run --rm --entrypoint /run.sh -v "$PWD/captures:/captures:ro" cfebms decode --file /captures/capture.bin --file-format raw
```

Review [the architecture notes](https://github.com/andrevza/cfebms/blob/main/docs/ARCHITECTURE.md)
and [development guidance](https://github.com/andrevza/cfebms/blob/main/AGENTS.md)
for more detail.

## License

Copyright (C) 2026 Andre van der Walt.

`cfebms` is licensed under the GNU General Public License v3.0 only
(`GPL-3.0-only`). See the complete terms in
[`LICENSE`](https://github.com/andrevza/cfebms/blob/main/LICENSE).
