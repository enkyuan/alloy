"""PEP 517 backend that syncs canonical contracts before delegating to setuptools.

The per-package copies under ``src/contracts/`` are generated build-time
artifacts (git-ignored); this hook guarantees they exist and match
``kaji/contracts/`` for every wheel/sdist build.
"""

from setuptools import build_meta  # noqa: I001
from setuptools.build_meta import *  # noqa: F401,F403

import subprocess
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_SYNC = _HERE.parent.parent / "tooling" / "integrations" / "contracts" / "beta.py"


def _sync_contracts() -> None:
    if _SYNC.is_file():
        subprocess.run([sys.executable, str(_SYNC), "--write"], check=True)


def build_wheel(wheel_directory, config_settings=None, metadata_directory=None):
    _sync_contracts()
    return build_meta.build_wheel(wheel_directory, config_settings, metadata_directory)


def build_sdist(sdist_directory, config_settings=None):
    _sync_contracts()
    return build_meta.build_sdist(sdist_directory, config_settings)


def build_editable(wheel_directory, config_settings=None, metadata_directory=None):
    _sync_contracts()
    return build_meta.build_editable(
        wheel_directory, config_settings, metadata_directory
    )
