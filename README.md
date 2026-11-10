# cfebms

![CFE BMS battery monitoring](https://raw.githubusercontent.com/andrevza/cfebms/main/docs/images/cfebms-readme.png)

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
MQTT broker in the App configuration. The App pulls a prebuilt image from
`andrevza/cfebms`; Home Assistant does not compile the App on the Raspberry Pi.
The App supports `aarch64` and `amd64`. Its `config.yaml` version is the exact
Docker tag Supervisor pulls, including the `v` prefix.

## Standalone Docker Compose

Copy the sample environment file, set reachable battery and MQTT addresses,
then build with source metadata and start the service:

```sh
cp .env.example .env
# Edit .env and set CFE_BATTERY_HOST and MQTT_HOST (and broker credentials if required).
./scripts/docker-build.sh
docker compose up -d cfebms
docker compose logs -f cfebms
```

The example uses reserved placeholder hostnames; replace them with addresses
reachable from the Docker bridge network. The service does not require
privileged mode or host networking. Do not run the standalone container and
the Home Assistant App at the same time; they share an MQTT device identity.

## Docker Hub images

Release images are built and published to Docker Hub only when a `v*` Git tag
is pushed. The App version in `config.yaml` must exactly match that tag, for
example `version: "v0.1.9"`; `image: "andrevza/cfebms"` contains no tag. The
workflow runs the Docker test suite first, builds `linux/amd64` and
`linux/arm64`, then combines them under the single tag `v0.1.9`. The image uses
the Home Assistant Python base image and supplies Supervisor's `/init`
entrypoint. It does not publish unprefixed version tags or `latest`.

To release, update `config.yaml` to the intended App version, commit and merge
that change to `main`, then push the matching Git tag. For example:

```sh
git switch main
# Set config.yaml to version: "v0.1.9" and commit the release change.
git tag v0.1.9
git push origin main
git push origin v0.1.9
```

The tag push starts the test and image publishing workflow. Check the GitHub
Actions run before pulling the new image.

Configure these repository Actions settings before the first release:

- Variable `DOCKERHUB_USERNAME`: the Docker Hub account or organization that
  owns the `cfebms` repository.
- Secret `DOCKERHUB_TOKEN`: a Docker Hub access token with permission to push
  to that repository.

After a release tag is pushed, pull the versioned image with:

```sh
docker pull andrevza/cfebms:v0.1.9
```

Docker and Supervisor select the matching platform image automatically. The
Docker `arm64` variant carries Home Assistant's `aarch64` architecture label.
Raspberry Pi devices need a 64-bit OS to use it.

## Development

Development, tests, and the diagnostic CLI run in Docker; no Python packages
need to be installed on the host. Run the offline test suite with:

```sh
docker compose run --build --rm test
```

Build the standalone service image with `scripts/docker-build.sh` to embed the
current Git revision and whether the working tree is dirty. Release images embed
the release commit, exact `v`-prefixed App version, and UTC build timestamp. The
startup identity is printed once at INFO level before MQTT connection attempts.
Check it in Home Assistant under the App's logs. The Python package version is
separate from the Home Assistant App version.
For dirty local builds, the log says `Source state: dirty`; that identifies that
the source differs from HEAD but does not describe those modifications.

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
