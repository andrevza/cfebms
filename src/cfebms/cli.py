"""Offline diagnostic command line interface."""

from __future__ import annotations

import argparse
import asyncio
import logging
import json
import sys
from pathlib import Path

from .protocol import decode_frame, parse_hex


def _format_result(data: bytes) -> str:
    result = decode_frame(data)
    return json.dumps(
        {
            "raw_frame_length": result.frame.length,
            "raw_hex": result.frame.data.hex(" "),
            "message_identification": result.frame.message_type or "unknown",
            "framing_validation": result.frame.status.value,
            "measurements": result.measurements,
            "unsupported_payload_hex": result.unsupported_payload.hex(" "),
            "warnings": result.warnings,
        },
        indent=2,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cfebms")
    commands = parser.add_subparsers(dest="command", required=True)
    decode = commands.add_parser("decode", help="analyze captured bytes offline")
    source = decode.add_mutually_exclusive_group(required=True)
    source.add_argument("--hex", help="hexadecimal bytes, separated by spaces")
    source.add_argument("--file", type=Path, help="capture file (raw bytes or hex text)")
    decode.add_argument("--file-format", choices=("raw", "hex"), default="raw")
    commands.add_parser("service", help="run the read-only TCP-to-MQTT service")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "service":
            from .config import Settings
            from .service import run_service

            settings = Settings.from_env()
            logging.basicConfig(
                level=getattr(logging, settings.log_level),
                format="%(asctime)s %(levelname)s %(name)s: %(message)s",
            )
            asyncio.run(run_service(settings))
            return 0
        if args.hex is not None:
            print(_format_result(parse_hex(args.hex)))
        elif args.file_format == "raw":
            print(_format_result(args.file.read_bytes()))
        else:
            for line_number, line in enumerate(args.file.read_text().splitlines(), start=1):
                if not line.strip() or line.lstrip().startswith("#"):
                    continue
                try:
                    data = parse_hex(line)
                except ValueError as exc:
                    raise ValueError(f"{args.file}:{line_number}: {exc}") from exc
                print(_format_result(data))
    except (OSError, ValueError) as exc:
        print(f"cfebms: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
