"""Decoded battery telemetry model."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TypeAlias

MeasurementValue: TypeAlias = float | int | str


@dataclass(frozen=True, slots=True)
class BatteryTelemetry:
    """One decoded record, retaining raw bytes not mapped by the decoder."""

    message_length: int
    values: dict[str, MeasurementValue] = field(default_factory=dict)
    provisional_fields: frozenset[str] = frozenset()
    unsupported_payload: bytes = b""
    warnings: tuple[str, ...] = ()
