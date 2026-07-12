"""argparse entry point."""

from __future__ import annotations

import argparse
import sys

from . import add as _add
from . import doctor as _doctor
from . import gen as _gen
from . import info as _info
from . import init as _init
from . import list_integrations as _list_integrations
from . import secret as _secret
from . import upgrade as _upgrade
from ._style import set_color_enabled


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="kaji", description="kaji CLI")
    parser.add_argument(
        "--no-color", action="store_true", help="disable ANSI color output"
    )
    parser.add_argument(
        "--verbose", action="store_true", help="include safe diagnostic detail"
    )
    sub = parser.add_subparsers(dest="command", required=True)
    _init.add_parser(sub)
    _gen.add_parser(sub)
    _add.add_parser(sub)
    _list_integrations.add_parser(sub)
    _info.add_parser(sub)
    _secret.add_parser(sub)
    _doctor.add_parser(sub)
    _upgrade.add_parser(sub)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    set_color_enabled(not args.no_color)
    return int(args.func(args))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
