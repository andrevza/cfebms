"""Decoded battery telemetry model."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TypeAlias

MeasurementValue: TypeAlias = float | int | str


@dataclass(frozen=True, slots=True)
class BatteryTelemetry:
    """Decoded measurements and diagnostic metadata for one retained frame."""

    message_length: int
    values: dict[str, MeasurementValue] = field(default_factory=dict)
    provisional_fields: frozenset[str] = frozenset()
    unsupported_payload: bytes = b""
    warnings: tuple[str, ...] = ()
    diagnostics: dict[str, MeasurementValue] = field(default_factory=dict)
