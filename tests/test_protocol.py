from __future__ import annotations

import pytest

from cfebms.frames import FrameAssembler, FrameStatus, cfe_frame_length, crc16_modbus
from cfebms.protocol import OBSERVED_INITIAL_SEQUENCE, analyze_frame, decode_cfe_telemetry, decode_frame, parse_hex


def make_frame(size: int) -> bytes:
    """Build a synthetic valid envelope for parser arithmetic tests only."""
    body = bytearray(size - 3)
    body[0] = 0x68
    crc = crc16_modbus(body)
    return bytes(body) + crc.to_bytes(2, "little") + b"\x16"


def test_parse_hex_with_spaces_and_prefixes() -> None:
    assert parse_hex("0x68 01 0c") == bytes((0x68, 0x01, 0x0C))


@pytest.mark.parametrize("invalid", ["0", "gg", "68 zz", "0x"])
def test_parse_hex_rejects_invalid_input(invalid: str) -> None:
    with pytest.raises(ValueError, match="invalid hexadecimal"):
        parse_hex(invalid)


def test_known_heartbeat_has_valid_modbus_crc() -> None:
    assert cfe_frame_length(OBSERVED_INITIAL_SEQUENCE) == 19
    heartbeat = decode_frame(OBSERVED_INITIAL_SEQUENCE)
    assert heartbeat.frame.status is FrameStatus.OBSERVED_SEQUENCE_MATCH
    assert heartbeat.frame.message_type == "heartbeat"


@pytest.mark.parametrize("size", [19, 35, 73, 97])
def test_cfe_frame_recognition_for_each_observed_size(size: int) -> None:
    frame = make_frame(size)
    assert cfe_frame_length(frame) == size
    classified = analyze_frame(frame)
    assert classified.status is FrameStatus.VALID_CFE
    if size in (35, 73, 97):
        assert classified.message_type == {35: "status", 73: "summary", 97: "detail"}[size]


def test_bad_crc_is_rejected() -> None:
    frame = bytearray(make_frame(35))
    frame[10] ^= 1
    assembler = FrameAssembler(cfe_frame_length)
    heartbeat = OBSERVED_INITIAL_SEQUENCE
    assert assembler.feed(bytes(frame) + heartbeat) == [heartbeat]


def test_stream_assembler_handles_fragmented_and_concatenated_mixed_frames() -> None:
    frames = [make_frame(size) for size in (35, 73, 97)]
    assembler = FrameAssembler(cfe_frame_length)
    first = frames[0] + frames[1][:12]
    assert assembler.feed(first) == [frames[0]]
    assert assembler.feed(frames[1][12:] + frames[2]) == frames[1:]
    assert assembler.pending == b""


def test_summary_decoder_uses_reference_summary_offsets() -> None:
    # Synthetic frame checks the ported calculations, not hardware behavior.
    raw = bytearray(make_frame(73))
    raw[13:15] = (5123).to_bytes(2, "little")
    raw[15:17] = (-125).to_bytes(2, "little", signed=True)
    raw[17:21] = (12000).to_bytes(4, "little")
    raw[21:25] = (12345).to_bytes(4, "little")
    raw[25:29] = (5678).to_bytes(4, "little")
    raw[29:33] = (9876).to_bytes(4, "little")
    raw[33] = 78
    raw[34] = 96
    raw[35:37] = (3600).to_bytes(2, "little")
    raw[37:39] = (3300).to_bytes(2, "little")
    raw[41] = 42
    raw[42] = 8
    raw[53] = 4
    raw[58:60] = (5600).to_bytes(2, "little")
    raw[60:62] = (1000).to_bytes(2, "little")
    raw[62:64] = (4500).to_bytes(2, "little")
    raw[64:66] = (2000).to_bytes(2, "little")
    raw[-3:-1] = crc16_modbus(raw[:-3]).to_bytes(2, "little")
    decoded = decode_cfe_telemetry(bytes(raw))
    assert decoded.values["voltage_v"] == 51.23
    assert decoded.values["current_a"] == -1.25
    assert decoded.values["power_w"] == 51.23 * -1.25
    assert decoded.values["charge_capacity_ah"] == 120
    assert decoded.values["discharge_capacity_ah"] == 123.45
    assert decoded.values["charge_energy_kwh"] == 56.78
    assert decoded.values["discharge_energy_kwh"] == 98.76
    assert decoded.values["soc_percent"] == 78
    assert decoded.values["soh_percent"] == 96
    assert decoded.values["operating_state"] == "CHARGE"
    assert decoded.values["charge_voltage_limit_v"] == 560
    assert decoded.values["charge_current_limit_a"] == 100
    assert decoded.values["discharge_voltage_limit_v"] == 450
    assert decoded.values["discharge_current_limit_a"] == 200


def test_detail_decoder_handles_dynamic_cell_and_temperature_counts() -> None:
    raw = bytearray(make_frame(97))
    raw[19:21] = (521).to_bytes(2, "little")
    raw[21:23] = (-230).to_bytes(2, "little", signed=True)
    raw[44] = 16
    cell_values = [3300 + index * 10 for index in range(16)]
    for offset, value in zip(range(45, 77, 2), cell_values):
        raw[offset:offset + 2] = value.to_bytes(2, "little")
    raw[77:79] = (3450).to_bytes(2, "little")
    raw[79:81] = (3300).to_bytes(2, "little")
    raw[81] = 15
    raw[82] = 0
    raw[83] = 3
    raw[84:87] = bytes((25, 26, 27))
    raw[87:93] = bytes((40, 5, 2, 0, 0, 0))
    raw[-3:-1] = crc16_modbus(raw[:-3]).to_bytes(2, "little")

    decoded = decode_cfe_telemetry(bytes(raw))
    assert decoded.values["voltage_v"] == 52.1
    assert decoded.values["current_a"] == -2.3
    assert decoded.values["cell_1_v"] == 3.3
    assert decoded.values["cell_16_v"] == 3.45
    assert decoded.values["cell_min_v"] == 3.3
    assert decoded.values["cell_max_v"] == 3.45
    assert decoded.values["cell_average_v"] == pytest.approx(3.375)
    assert decoded.values["cell_delta_mv"] == 150
    assert decoded.values["cell_max_index"] == 16
    assert decoded.values["cell_min_index"] == 1
    assert decoded.values["temperature_1_c"] == 25
    assert decoded.values["temperature_3_c"] == 27
    assert decoded.values["temperature_max_c"] == 27
    assert decoded.values["temperature_min_c"] == 25


def test_detail_decoder_does_not_read_dynamic_cells_into_crc() -> None:
    raw = bytearray(make_frame(97))
    raw[44] = 255
    raw[-3:-1] = crc16_modbus(raw[:-3]).to_bytes(2, "little")
    decoded = decode_cfe_telemetry(bytes(raw))
    assert "cell_1_v" not in decoded.values
    assert "temperature_1_c" not in decoded.values


def test_detail_decoder_respects_non_default_dynamic_counts() -> None:
    raw = bytearray(make_frame(97))
    raw[44] = 8
    values = [3400 + i for i in range(8)]
    for offset, value in zip(range(45, 61, 2), values):
        raw[offset:offset + 2] = value.to_bytes(2, "little")
    raw[67] = 2
    raw[68:70] = bytes((22, 24))
    raw[70:77] = bytes((24, 22, 1, 0, 0, 0, 0))
    raw[-3:-1] = crc16_modbus(raw[:-3]).to_bytes(2, "little")
    decoded = decode_cfe_telemetry(bytes(raw))
    assert decoded.values["cell_8_v"] == 3.407
    assert "cell_9_v" not in decoded.values
    assert decoded.values["temperature_1_c"] == 22
    assert decoded.values["temperature_2_c"] == 24
    assert "temperature_3_c" not in decoded.values
