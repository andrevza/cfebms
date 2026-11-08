# CFE BMS Home Assistant App

The App monitors a CFE battery over TCP and publishes measurements through the
MQTT broker configured below. It supports Home Assistant App architectures
`aarch64` and `amd64` and uses the same service, MQTT topics and entity
identifiers as the standalone Docker Compose deployment.

The currently supported battery target is the CFE-5100S. No other CFE model
is claimed as supported.

## Install

1. In Home Assistant, open **Settings → Apps → App store → ⋮ → Repositories**.
2. Add `https://github.com/andrevza/cfebms` and submit it.
3. Find **CFE BMS** in the App store and install it.
4. Open the App's **Configuration** page and set the battery host and MQTT
   broker values. Save the options, then start the App.

The repository must be available on GitHub for Supervisor to fetch it. This
project packaging has not yet been tested by installing it into a live
Supervisor instance.

## Configure

Set `cfe_battery_host` to the IP address or DNS name of the battery or its TCP
bridge. The default TCP port is `6868`. Set `mqtt_host` and `mqtt_port` to the
broker already used by Home Assistant. Fill in both MQTT username and password
when the broker requires authentication; leave both empty for an anonymous
broker. The password field is stored as a password option by the App schema.

Example values (replace them with addresses and credentials for your network):

```yaml
cfe_battery_host: battery.example.com
cfe_battery_port: 6868
cfe_connect_timeout: 5.0
cfe_read_timeout: 10.0
cfe_reconnect_delay: 5.0
cfe_stale_after: 30.0
mqtt_host: mqtt.example.com
mqtt_port: 1883
mqtt_username: ""
mqtt_password: ""
mqtt_discovery_prefix: homeassistant
mqtt_base_topic: cfebms
log_level: INFO
heartbeat_log_interval_min: 60
```

Documentation-only address examples are `192.0.2.10` for a battery bridge and
`192.0.2.20` for an MQTT broker; these addresses are reserved for examples and
must be replaced in a real installation.

All App options map to the existing service environment settings. Connection
timeouts, stale telemetry duration, reconnect delay, discovery prefix, base
topic and logging level use their current service defaults. Set
`heartbeat_log_interval_min` to `0` to disable periodic operational heartbeat
logging.

## Operate

- Start and stop the App from its Home Assistant App page.
- Read runtime and connection logs in the App's **Logs** tab.
- After the MQTT discovery publication, find the **CFE Battery** device under
  **Settings → Devices & services → MQTT → Devices**.
- Upgrade from the App page after a new version is available in the repository.
  Existing MQTT discovery topics and entity IDs are retained across upgrades.

Stop the standalone `cfebms` container before starting the App. Running both
instances at once causes them to share the MQTT device and availability
identity.

## Troubleshoot

- **Battery connection failures:** confirm `cfe_battery_host` resolves from the
  Home Assistant host and that the TCP bridge accepts connections on port
  `6868` (or the configured port). Review the App logs for the connection
  error and retry messages.
- **MQTT connection failures:** confirm the broker host/port and credentials.
  The MQTT integration must be configured in Home Assistant and MQTT discovery
  must be enabled. The configured discovery prefix must match the broker's
  discovery convention.
- **No battery device:** check the App logs for MQTT connection and discovery
  publication messages, then verify the broker is reachable from Home
  Assistant.
- **Stale/unavailable readings:** check the battery TCP connection and App logs.
  The service marks readings unavailable when telemetry becomes stale.

Operational heartbeat reports appear in the App logs at the configured
`heartbeat_log_interval_min`. They include connection health, received frame
counts, and the latest decoded SOC and pack voltage. Set the interval to `0`
to turn off periodic reports.

The App is TCP-only. It does not request privileged mode, host networking,
serial access or device mounts. The manifest has not been validated in a live
Supervisor installation yet.

## Standalone Docker Compose

For the quick-start commands, see the standalone deployment section in
[`README.md`](README.md). Configure battery and broker values as described
above, and do not run the container and the Home Assistant App simultaneously.
