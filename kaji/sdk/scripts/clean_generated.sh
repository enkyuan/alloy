#!/usr/bin/env bash
set -euo pipefail

find src tests -type d -name __pycache__ -prune -exec rm -rf {} +
find src tests -type f \( -name '*.pyc' -o -name '*.pyo' \) -delete
