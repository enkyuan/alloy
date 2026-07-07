#!/usr/bin/env bash
set -euo pipefail

find src tests -type d -name __pycache__ -prune -exec rm -rf {} +
find src tests -type f \( -name '*.pyc' -o -name '*.pyo' \) -delete
rm -rf .pytest_cache .ruff_cache .mypy_cache .ty .coverage htmlcov
