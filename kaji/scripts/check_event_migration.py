#!/usr/bin/env python3
"""Read-only compatibility preflight for pre-beta stored-event JSONL logs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from kaji.infra.events.errors import EventSchemaIncompatibleError
from kaji.infra.events.schemas import validate_stored_event_python


def check_log(path: Path) -> list[tuple[int, str]]:
    failures: list[tuple[int, str]] = []
    with path.open("rb") as log:
        for line_number, raw_line in enumerate(log, start=1):
            if not raw_line.strip():
                continue
            try:
                document = json.loads(raw_line.decode("utf-8"))
                validate_stored_event_python(document)
            except (json.JSONDecodeError, UnicodeDecodeError):
                failures.append((line_number, "/"))
            except EventSchemaIncompatibleError as error:
                failures.append((line_number, error.path))
    return failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Report pre-beta stored-event JSONL rows incompatible with wire version 1.0."
    )
    parser.add_argument("log", type=Path)
    args = parser.parse_args(argv)
    try:
        failures = check_log(args.log)
    except OSError as error:
        print(f"FAIL: {args.log}: {error}", file=sys.stderr)
        return 2
    if failures:
        for line_number, path in failures:
            print(
                f"{args.log}:{line_number}: EVENT_SCHEMA_INCOMPATIBLE {path}",
                file=sys.stderr,
            )
        return 1
    print(f"OK: {args.log} is compatible with stored event wire version 1.0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
