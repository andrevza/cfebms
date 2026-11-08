"""CFE frame validation and evidence-backed telemetry decoding."""

from __future__ import annotations

from dataclasses import dataclass

from .frames import FrameStatus, RawFrame, is_valid_cfe_frame
from .models import BatteryTelemetry, MeasurementValue


OBSERVED_INITIAL_SEQUENCE = bytes.fromhex(
    "68 01 0c 00 01 b0 84 57 01 0a 01 00 00 00 00 04 00 c3 16"
)
OBSERVED_TELEMETRY_LENGTHS = (35, 73, 97)


@dataclass(frozen=True, slots=True)
class DecodedMessage:
    frame: RawFrame
    measurements: dict[str, int | float | str]
    unsupported_payload: bytes
    warnings: tuple[str, ...]


def parse_hex(text: str) -> bytes:
    """Parse whitespace-separated hex, accepting optional ``0x`` prefixes."""
    tokens = text.split()
    stripped = [token[2:] if token.lower().startswith("0x") else token for token in tokens]
    if any(not token for token in stripped):
        raise ValueError("invalid hexadecimal input: empty 0x token")
    normalized = " ".join(stripped)
    try:
        return bytes.fromhex(normalized)
    except ValueError as exc:
        raise ValueError(f"invalid hexadecimal input: {exc}") from exc


def analyze_frame(data: bytes) -> RawFrame:
    """Validate a known CFE frame and identify the exact observed heartbeat."""
    if data == OBSERVED_INITIAL_SEQUENCE and is_valid_cfe_frame(data):
        return RawFrame(data, FrameStatus.OBSERVED_SEQUENCE_MATCH, "heartbeat")
    if is_valid_cfe_frame(data):
        kind = {35: "status", 73: "summary", 97: "detail"}.get(len(data), "telemetry")
        return RawFrame(data, FrameStatus.VALID_CFE, kind)
    if len(data) < len(OBSERVED_INITIAL_SEQUENCE) and OBSERVED_INITIAL_SEQUENCE.startswith(data):
        return RawFrame(data, FrameStatus.INCOMPLETE_OBSERVED_SEQUENCE)
    return RawFrame(data, FrameStatus.UNKNOWN)


def decode_frame(data: bytes) -> DecodedMessage:
    """Validate framing and decode mappings whose representation is established."""
    frame = analyze_frame(data)
    if frame.status is FrameStatus.OBSERVED_SEQUENCE_MATCH:
        return DecodedMessage(frame, {}, b"", ())
    telemetry = decode_cfe_telemetry(data)
    return DecodedMessage(frame, dict(telemetry.values), telemetry.unsupported_payload, telemetry.warnings)


def decode_cfe_telemetry(data: bytes) -> BatteryTelemetry:
    """Port SUMMARY and DETAIL decoding from the supplied CFE reference."""
    if not is_valid_cfe_frame(data) or data == OBSERVED_INITIAL_SEQUENCE:
        return BatteryTelemetry(len(data), {}, frozenset(), data, ("Invalid or non-telemetry CFE frame.",))

    values: dict[str, MeasurementValue] = {}
    if len(data) == 73:
        values["voltage_v"] = u16(data, 13) / 100
        values["current_a"] = s16(data, 15) / 100
        values["power_w"] = values["voltage_v"] * values["current_a"]
        values["charge_capacity_ah"] = u32(data, 17) / 100
        values["discharge_capacity_ah"] = u32(data, 21) / 100
        values["charge_energy_kwh"] = u32(data, 25) / 100
        values["discharge_energy_kwh"] = u32(data, 29) / 100
        values["soc_percent"] = data[33]
        values["soh_percent"] = data[34]
        values["cell_max_v"] = u16(data, 35) / 1000
        values["cell_min_v"] = u16(data, 37) / 1000
        values["temperature_max_c"] = data[41]
        values["temperature_min_c"] = data[42]
        values["operating_state"] = _state_name(data[53])
        for field, offset, divisor in (
            ("charge_voltage_limit_v", 58, 10),
            ("charge_current_limit_a", 60, 10),
            ("discharge_voltage_limit_v", 62, 10),
            ("discharge_current_limit_a", 64, 10),
        ):
            values[field] = u16(data, offset) / divisor
    elif len(data) == 97:
        values["voltage_v"] = u16(data, 19) / 10
        values["current_a"] = s16(data, 21) / 100
        values["power_w"] = values["voltage_v"] * values["current_a"]
        cell_count = data[44]
        offset = 45
        crc_start = len(data) - 3
        cell_end = offset + cell_count * 2
        if cell_count and cell_end + 7 <= crc_start:
            cells = [u16(data, pos) / 1000 for pos in range(offset, cell_end, 2)]
            for index, voltage in enumerate(cells, 1):
                values[f"cell_{index}_v"] = voltage
            cell_mv = [int(round(voltage * 1000)) for voltage in cells]
            values["cell_max_v"] = max(cells)
            values["cell_min_v"] = min(cells)
            values["cell_average_v"] = sum(cells) / len(cells)
            values["cell_delta_mv"] = max(cell_mv) - min(cell_mv)
            values["cell_max_index"] = cell_mv.index(max(cell_mv)) + 1
            values["cell_min_index"] = cell_mv.index(min(cell_mv)) + 1
            temp_count = data[cell_end + 6]
            temp_start = cell_end + 7
            temp_end = temp_start + temp_count
            if temp_end + 7 <= crc_start:
                temperatures = list(data[temp_start:temp_end])
                for index, temperature in enumerate(temperatures, 1):
                    if index > 3:
                        break
                    values[f"temperature_{index}_c"] = temperature
                values["temperature_max_c"] = max(temperatures) if temperatures else data[temp_end]
                values["temperature_min_c"] = min(temperatures) if temperatures else data[temp_end + 1]
                # The original decoder computes cell extrema and numbering
                # from the individual cell list, not the reported raw fields.
        # Detail frames carry no SOC/SOH or operating-state summary mapping.
    return BatteryTelemetry(len(data), values, frozenset(), data, ())


def u16(frame: bytes, offset: int) -> int:
    return int.from_bytes(frame[offset:offset + 2], "little", signed=False)


def s16(frame: bytes, offset: int) -> int:
    return int.from_bytes(frame[offset:offset + 2], "little", signed=True)


def u32(frame: bytes, offset: int) -> int:
    return int.from_bytes(frame[offset:offset + 4], "little", signed=False)


def _state_name(code: int) -> str:
    return {2: "IDLE", 3: "DISCHARGE", 4: "CHARGE"}.get(code, f"UNKNOWN({code})")
