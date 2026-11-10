# CFE protocol implementation status

`cfebms` ports the working CFE-5100S reference decoder used during
development. That reference script is not included in this repository.
The parser accepts HEARTBEAT (19 bytes), STATUS (35), SUMMARY (73), and DETAIL
(97) frames. It validates CRC-16/MODBUS over all bytes before the little-endian
CRC immediately preceding the final `0x16` byte. It handles fragmented and
concatenated streams and resynchronizes after rejected input.

The service echoes a received CRC-valid HEARTBEAT exactly. It sends no other
battery commands. SUMMARY and DETAIL measurements, offsets, representations,
and scales are documented in [`PROTOCOL_RESEARCH.md`](PROTOCOL_RESEARCH.md) and
published through the existing MQTT/Home Assistant integration. STATUS is
recognized but has no decoded measurements in the reference implementation.

The only frame bytes available in the repository are the observed heartbeat.
No sanitized telemetry frames are checked in, so decoder unit tests exercise
the port using synthetic frames and do not independently validate telemetry
against a live battery capture.

SOC is decoded from SUMMARY byte 33 only. Unknown bytes, extra temperature
candidates, and diagnostic flags are retained in the raw frame and are not
published as measurements. SUMMARY and DETAIL RTC bytes 9–12 are decoded as
little-endian Unix seconds and kept as diagnostic metadata, separate from
publishable measurements. The periodic health report renders the timestamp in
UTC ISO-8601; it is not published as telemetry.
