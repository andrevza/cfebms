# Remaining CFE protocol questions

The parser supports the observed frame envelope and heartbeat. SUMMARY and
DETAIL mappings have been ported from the working CFE-5100S decoder used
during development. The reference script and sanitized telemetry captures are
not included in this repository, so fixture-based hardware verification is
not available here.

## Evidence still needed

- Sanitized 35-, 73-, and 97-byte frames with capture direction and
  independently observed battery values to verify the ported decoder.
- Model and firmware scope for each mapping.
- Independent verification of the decoder's SOC and other measurement scales
  against known battery readings.

The included heartbeat bytes validate CRC-16/MODBUS with the CRC in
low-byte-first order immediately before `0x16`. The exact heartbeat is the
only message the service echoes. No other battery commands are sent.
