# CFE BMS Home Assistant App

The App monitors a supported CFE battery over TCP and publishes telemetry to
your MQTT broker. Home Assistant discovers the battery sensors automatically.
The currently supported battery target is the CFE-5100S.

## Install

1. In Home Assistant, open **Settings → Apps → App store → ⋮ → Repositories**.
2. Add `https://github.com/andrevza/cfebms` and submit it.
3. Find **CFE BMS** in the App store and install it.
4. Configure the MQTT broker and battery connection below, then save and start
   the App.

## Configuration

The App presents six connection settings by default. Advanced
settings are optional and can be shown by enabling **Show unused optional
configuration options** on the App's Configuration page. Omitted advanced
settings use the Python application's defaults. Existing saved advanced
settings remain supported.

The App stores its options in Supervisor-managed configuration. Password
fields are declared as password options and are not logged by cfebms.

### MQTT connection

| Key | Purpose | Required | Accepted value | Default |
| --- | --- | --- | --- | --- |
| `mqtt_host` | MQTT broker hostname or IP address. | Yes | String | App default is blank and must be set. Python fallback, used only if no value is provided, is `mqtt.example.com`. |
| `mqtt_port` | MQTT broker TCP port. | Yes | Integer, 1–65535 | Supervisor: `1883`; Python: `1883`. |
| `mqtt_username` | Broker username; leave blank for an anonymous broker. Username and password must both be set or both be blank. | No | Optional string | Supervisor: blank; Python: unset (`None`). |
| `mqtt_password` | Broker password; hidden by the Home Assistant configuration form. | No | Optional password | Supervisor: blank; Python: unset (`None`). |
| `mqtt_discovery_prefix` | MQTT Home Assistant discovery topic prefix. | No | Optional string | Python: `homeassistant`. |
| `mqtt_base_topic` | Root topic used for cfebms telemetry and availability. | No | Optional string | Python: `cfebms`. |

The discovery prefix must match the prefix configured for Home Assistant's MQTT
integration. Keep the base topic unchanged unless you need a different MQTT
topic namespace.

### Battery TCP connection

| Key | Purpose | Required | Accepted value | Default |
| --- | --- | --- | --- | --- |
| `cfe_battery_host` | Battery or TCP bridge hostname/IP. | Yes | String | App default is blank; provide the address for your battery. Python requires this value. |
| `cfe_battery_port` | Battery TCP port. | Yes | Integer, 1–65535 | Supervisor: `6868`; Python: `6868`. |
| `cfe_connect_timeout` | Maximum time allowed for a TCP connection attempt. | No | Optional number, 0.1–86400 seconds | Python: `5.0` seconds. |
| `cfe_read_timeout` | Maximum wait for incoming TCP data before the read operation times out. | No | Optional number, 0.1–86400 seconds | Python: `10.0` seconds. |
| `cfe_reconnect_delay` | Delay before retrying a failed battery connection. | No | Optional number, 0.1–86400 seconds | Python: `5.0` seconds. |
| `cfe_stale_after` | Time without battery TCP data before the connection is considered stale. | No | Optional number, 0.1–86400 seconds | Python: `30.0` seconds. |

### Logging and diagnostics

| Key | Purpose | Required | Accepted value | Default |
| --- | --- | --- | --- | --- |
| `log_level` | Application logging verbosity. | No | Optional `DEBUG`, `INFO`, `WARNING`, `ERROR`, or `CRITICAL` | Python: `INFO`. |
| `heartbeat_log_interval_min` | Interval, in minutes, for operational health reports containing connection status, frame counts, SOC, and voltage. | No | Optional integer, 0–10080 | Python: `60` minutes. Set to `0` to disable periodic reports. |

Periodic operational reports do not control battery communication or MQTT
publishing. Setting the interval to `0` disables only these health summary
logs; CFE protocol heartbeat acknowledgements continue normally. Increasing
the interval reduces routine log output.

## Minimal configuration example

Enter the six visible connection settings. Replace documentation-only hosts and
credentials with values for your network. Leave MQTT credentials blank when
your broker allows anonymous access.

```yaml
cfe_battery_host: 192.0.2.10
cfe_battery_port: 6868
mqtt_host: 192.0.2.20
mqtt_port: 1883
mqtt_username: ""
mqtt_password: ""
```

The addresses in this example are reserved for documentation and will not
connect to a real battery or broker.

## Advanced configuration example

Enable **Show unused optional configuration options** to expose advanced
settings. Only override the values you need; omitted options retain the Python
defaults.

```yaml
cfe_connect_timeout: 8.0
cfe_reconnect_delay: 10.0
mqtt_discovery_prefix: homeassistant
log_level: DEBUG
heartbeat_log_interval_min: 0
```

## Operation and troubleshooting

- Read connection and decoding messages in the App's **Logs** tab.
- Find the discovered **CFE Battery** device under **Settings → Devices &
  services → MQTT → Devices**.
- If the battery does not connect, verify the battery/bridge address and TCP
  port are reachable from the Home Assistant host.
- If MQTT does not connect, check the broker address, port and credentials. The
  Home Assistant MQTT integration and its discovery prefix must be configured
  for the same broker.
- If readings become unavailable, check the battery TCP connection and logs
  for stale telemetry reports.

Stop the standalone `cfebms` container before starting the App. Running both
instances at once makes them share the same MQTT device and availability
identity.

The App does not require privileged mode, host networking, serial access, or
device mounts.

## Standalone Docker Compose

Standalone deployment instructions are in [`README.md`](README.md). Configure
the battery and MQTT connection settings as above, and avoid running the App
and standalone container simultaneously.
