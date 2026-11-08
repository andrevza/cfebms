# Development instructions

## Reference project location

- When reviewing the bmspace implementation, first look for the sibling
  checkout at `../bmspace/` relative to this repository root.
- If that checkout is unavailable, use
  [andrevza/bmspace](https://github.com/andrevza/bmspace) as the reference.
- Do not depend on a developer-specific home directory or absolute path.

## Scope and safety

- This project implements the CFE battery protocol. Do not copy or adapt
  bmspace protocol code; that project targets a different protocol.
- Keep battery communication read-only. Do not add write commands, settings
  changes, firmware updates or control operations.
- Treat protocol findings as `confirmed`, `inferred` or `unknown`, and cite
  capture or experiment evidence where available. Implement documented
  historical mappings that have enough representation details; keep unresolved
  values unavailable and preserve undecoded bytes.
- Sanitize captures and configuration examples. Do not commit credentials,
  private addresses, serial numbers, or identifying metadata.

## Design

- Keep frame assembly, protocol decoding, telemetry models, service
  orchestration and MQTT/Home Assistant integration in separate modules.
- TCP connection handling currently lives in `service.py`; do not add a
  transport abstraction without a concrete requirement.
- Frame handling must support observed CFE frame lengths, CRC validation,
  fragmented and concatenated input, and resynchronization.
- Prefer standard-library abstractions and explicit types. Add dependencies
  only for a concrete need.
- Keep the library usable without MQTT, Docker or Home Assistant installed.
- Run development, tests and CLI examples in Docker. Do not install Python
  packages or create virtual environments on the host for this repository.
- Make operational defaults conservative, including timeouts and reconnect
  behavior. Do not hide malformed or unsupported input.
- Publish only verified fields by default. Unsupported entities must remain
  unavailable, including after retained values go stale.

## Changes and evidence

- Update `docs/PROTOCOL.md` and `docs/OPEN_QUESTIONS.md` as evidence changes.
- Add deterministic offline tests for every implemented parser/decoder
  behavior. Prefer sanitized binary fixtures with provenance notes.
- Do not claim device compatibility beyond tested models and firmware.
- Do not publish, push, create a remote repository or release without explicit
  user approval.
- Respect GPL-3.0 obligations if any bmspace code is ever reused. Prefer
  architectural inspiration only and document provenance for copied code.
