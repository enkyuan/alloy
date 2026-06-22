"""argparse entry point."""

from __future__ import annotations

import argparse
import sys

from . import doctor as _doctor
from . import gen as _gen
from . import info as _info
from . import init as _init
from . import secret as _secret


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agentkit", description="agentkit CLI")
    sub = parser.add_subparsers(dest="command", required=True)
    _init.add_parser(sub)
    _gen.add_parser(sub)
    _info.add_parser(sub)
    _secret.add_parser(sub)
    _doctor.add_parser(sub)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
