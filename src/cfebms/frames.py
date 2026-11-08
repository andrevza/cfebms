"""CFE frame validation and incremental TCP stream assembly."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Callable


class FrameStatus(StrEnum):
    OBSERVED_SEQUENCE_MATCH = "matches_observed_initial_sequence"
    INCOMPLETE_OBSERVED_SEQUENCE = "prefix_of_observed_initial_sequence"
    UNKNOWN = "unknown_unvalidated"
    VALID_CFE = "valid_cfe_frame"


@dataclass(frozen=True, slots=True)
class RawFrame:
    """Unmodified bytes and limited evidence-based classification."""

    data: bytes
    status: FrameStatus
    message_type: str | None = None

    @property
    def length(self) -> int:
        return len(self.data)


@dataclass(frozen=True, slots=True)
class BufferDiagnostic:
    code: str
    detail: str


FrameLength = Callable[[bytes], int | None]


CFE_FRAME_LENGTHS = (19, 35, 73, 97)
CFE_START = 0x68
CFE_END = 0x16


def crc16_modbus(data: bytes) -> int:
    """Return the standard CRC-16/MODBUS value (wire order is low byte first)."""
    crc = 0xFFFF
    for value in data:
        crc ^= value
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc


def is_valid_cfe_frame(data: bytes) -> bool:
    """Validate the observed CFE envelope and trailing MODBUS CRC.

    The observed heartbeat establishes CRC over bytes before the two-byte CRC;
    the CRC is little-endian and followed by the 0x16 terminator.
    """
    if len(data) not in CFE_FRAME_LENGTHS or data[0] != CFE_START or data[-1] != CFE_END:
        return False
    expected = int.from_bytes(data[-3:-1], "little")
    return crc16_modbus(data[:-3]) == expected


def cfe_frame_length(buffer: bytes) -> int | None:
    """Identify complete observed CFE frames by size, terminator and CRC."""
    if not buffer:
        return None
    if buffer[0] != CFE_START:
        return 0
    for size in CFE_FRAME_LENGTHS:
        if len(buffer) >= size:
            candidate = buffer[:size]
            if is_valid_cfe_frame(candidate):
                return size
            # A terminator immediately followed by a fresh start marks a
            # rejected frame boundary and permits prompt recovery after CRC
            # corruption without waiting for the maximum frame size.
            if candidate[-1] == CFE_END and len(buffer) > size and buffer[size] == CFE_START:
                return 0
    if len(buffer) >= CFE_FRAME_LENGTHS[-1]:
        return 0
    return None


class FrameAssembler:
    """Accumulate arbitrary stream chunks using a frame recognition rule.

    ``frame_length`` returns a complete frame length, ``None`` when more bytes
    are needed, or a non-positive length to flag one malformed leading byte.
    The runtime supplies ``cfe_frame_length`` to recognize observed CFE frames.
    """

    def __init__(
        self,
        frame_length: FrameLength | None = None,
        *,
        max_buffer_size: int = 65536,
    ) -> None:
        if max_buffer_size < 1:
            raise ValueError("max_buffer_size must be positive")
        self._frame_length = frame_length
        self._max_buffer_size = max_buffer_size
        self._buffer = bytearray()
        self.diagnostics: list[BufferDiagnostic] = []

    @property
    def pending(self) -> bytes:
        return bytes(self._buffer)

    def feed(self, chunk: bytes) -> list[bytes]:
        """Add a stream chunk and return any complete frames recognized."""
        self.diagnostics.clear()
        self._buffer.extend(chunk)
        if len(self._buffer) > self._max_buffer_size:
            excess = len(self._buffer) - self._max_buffer_size
            del self._buffer[:excess]
            self.diagnostics.append(
                BufferDiagnostic("buffer_limit", f"discarded {excess} oldest byte(s)")
            )

        frames: list[bytes] = []
        if self._frame_length is None:
            return frames

        while self._buffer:
            try:
                size = self._frame_length(bytes(self._buffer))
            except (ValueError, IndexError) as exc:
                size = 0
                reason = str(exc) or exc.__class__.__name__
            else:
                reason = "framing rule rejected leading byte"

            if size is None:
                break
            if size <= 0:
                del self._buffer[0]
                self.diagnostics.append(BufferDiagnostic("malformed_input", reason))
                continue
            if size > self._max_buffer_size:
                del self._buffer[0]
                self.diagnostics.append(
                    BufferDiagnostic("invalid_frame_size", f"reported size {size} exceeds limit")
                )
                continue
            if len(self._buffer) < size:
                break
            frames.append(bytes(self._buffer[:size]))
            del self._buffer[:size]
        return frames
