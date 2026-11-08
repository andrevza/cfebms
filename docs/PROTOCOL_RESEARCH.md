# Ported CFE-5100S mappings

This table records the behavior ported from the working CFE-5100S reference
decoder used during development. It documents that decoder's offsets and
scales; the reference script and sanitized STATUS/SUMMARY/DETAIL captures are
not included in this repository for independent fixture verification.

## Framing

Frames begin with `0x68` and end with `0x16`. CRC-16/MODBUS covers all bytes
before the two-byte CRC; CRC bytes are little-endian immediately before the
terminator. Accepted lengths: HEARTBEAT 19, STATUS 35, SUMMARY 73, DETAIL 97.
Only a CRC-valid, exact HEARTBEAT is echoed.

## SUMMARY (73 bytes)

| Field | Offset(s) | Representation | Scaling |
|---|---:|---|---:|
| Pack voltage | 13–14 | u16 little-endian | /100 V |
| Pack current | 15–16 | s16 little-endian | /100 A |
| Charge capacity | 17–20 | u32 little-endian | /100 Ah |
| Discharge capacity | 21–24 | u32 little-endian | /100 Ah |
| Charge energy | 25–28 | u32 little-endian | /100 kWh |
| Discharge energy | 29–32 | u32 little-endian | /100 kWh |
| SOC / SOH | 33 / 34 | u8 | percent |
| Reported max/min cell voltage | 35–36 / 37–38 | u16 little-endian | /1000 V |
| Reported max/min temperature | 41 / 42 | u8 | °C |
| Operating state | 53 | u8: 2 idle, 3 discharge, 4 charge | enum |
| Charge voltage/current limits | 58–59 / 60–61 | u16 little-endian | /10 V / /10 A |
| Discharge voltage/current limits | 62–63 / 64–65 | u16 little-endian | /10 V / /10 A |

## DETAIL (97 bytes)

Pack voltage is u16 little-endian at 19–20, scaled by 10 V; signed current is
s16 little-endian at 21–22, scaled by 100 A. Cell count is byte 44. That many
u16 little-endian millivolt values begin at byte 45. The decoder computes cell
minimum, maximum, average, voltage delta, and one-based cell numbers for the
minimum and maximum values, matching the reference script.

After the cell list are two reported u16 cell extrema, two reported cell
indexes, then a temperature count and that many unsigned Celsius bytes. The
next two bytes are reported maximum and minimum temperatures. The reference
also reads additional temperature indexes/candidates and a diagnostic flag;
these are not published as measurements. Dynamic counts are bounds-checked
against the CRC start. Only the first three temperatures are exposed.

## Limits

SOC is present in SUMMARY only. STATUS frames are recognized but the reference
does not decode measurements from them. Synthetic tests exercise the ported
logic and CRC behavior; they do not substitute for sanitized battery captures.
