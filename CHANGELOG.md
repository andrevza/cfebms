# Changelog

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
