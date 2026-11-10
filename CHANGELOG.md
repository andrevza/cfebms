# Changelog

## 0.1.7

- Delay Home Assistant discovery and battery measurement publication until a
  CRC-valid SUMMARY frame has decoded successfully.
- Restore retained discovery after MQTT reconnects or Home Assistant birth,
  keeping sensor availability offline until fresh measurements arrive.

## 0.1.6

- Add battery RTC diagnostics from SUMMARY and DETAIL frames to periodic health
  reports without publishing RTC metadata as MQTT telemetry.

## 0.1.5

- Keep operational health-report deadlines out of the TCP read timeout and
  reconnect retry wait so reporting cannot cancel a pending battery read.

## 0.1.4

- Echo every CRC-valid 19-byte CFE heartbeat exactly as received, matching the
  working reference client.
- Add DEBUG timing details to existing periodic health reports for TCP session
  age, recent receive/frame/ack timing, and report execution duration.

## 0.1.3

- Show only the battery and MQTT connection settings by default in the Home
  Assistant App configuration.
- Move tuning, topic, and logging settings to optional advanced configuration.
- Document all App settings, defaults, and configuration examples.

## 0.1.2

- Read Supervisor-managed App options before dropping privileges, then run the
  cfebms service as the non-root service account.

## 0.1.1

- Build the Home Assistant App from the pinned Home Assistant Python base image
  and make its Dockerfile compatible with Alpine Linux.

## 0.1.0

- Initial CFE BMS Home Assistant App version, providing read-only CFE battery
  telemetry over TCP and MQTT publishing with Home Assistant MQTT discovery.
