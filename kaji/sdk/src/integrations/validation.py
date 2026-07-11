"""Cached shared-contract validation for integration manifests and indexes."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from functools import lru_cache
from pathlib import Path
from typing import Any, ClassVar, Literal, cast

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.protocols import Validator


IntegrationValidationCode = Literal["INTEGRATION_SCHEMA_INVALID"]
SchemaKind = Literal["manifest", "index"]


def json_pointer(path: Iterable[object]) -> str:
    parts = list(path)
    if not parts:
        return "/"
    escaped = (str(part).replace("~", "~0").replace("/", "~1") for part in parts)
    return "/" + "/".join(escaped)


class ManifestError(ValueError):
    """Raised when an integration registry contract is malformed."""


class IntegrationValidationError(ManifestError):
    """Normalized cross-SDK integration contract failure."""

    def __init__(
        self, code: IntegrationValidationCode, path: str, message: str
    ) -> None:
        self.code = code
        self.path = path
        self.message = message
        super().__init__(message)

    def normalized(self) -> dict[str, str]:
        return {"code": self.code, "path": self.path}


class ManifestValidationError(IntegrationValidationError):
    code: ClassVar[Literal["INTEGRATION_SCHEMA_INVALID"]] = "INTEGRATION_SCHEMA_INVALID"

    def __init__(self, path: str, message: str) -> None:
        super().__init__(self.code, path, message)


class IndexValidationError(IntegrationValidationError):
    code: ClassVar[Literal["INTEGRATION_SCHEMA_INVALID"]] = "INTEGRATION_SCHEMA_INVALID"

    def __init__(self, path: str, message: str) -> None:
        super().__init__(self.code, path, message)


def _schema_path(kind: SchemaKind) -> Path:
    filename = "schema.json" if kind == "manifest" else "index.schema.json"
    return Path(__file__).resolve().parent / "registry" / filename


@lru_cache(maxsize=2)
def _schema_validator(kind: SchemaKind) -> Validator:
    schema = json.loads(_schema_path(kind).read_text())
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=FormatChecker())


def _validate_schema(document: object, kind: SchemaKind) -> None:
    errors = sorted(
        _schema_validator(kind).iter_errors(document),
        key=lambda error: (
            json_pointer(error.absolute_path),
            json_pointer(error.absolute_schema_path),
        ),
    )
    if not errors:
        return
    error = errors[0]
    path = json_pointer(error.absolute_path)
    subject = "Integration manifest" if kind == "manifest" else "Integration index"
    message = f"{subject} failed {error.validator} validation at {path}"
    if kind == "manifest":
        raise ManifestValidationError(path, message)
    raise IndexValidationError(path, message)


def validate_manifest_document(document: object) -> None:
    """Validate one manifest against the canonical schema and set semantics."""
    _validate_schema(document, "manifest")
    manifest = cast(Mapping[str, Any], document)
    seen: set[str] = set()
    for index, tool in enumerate(cast(list[Mapping[str, Any]], manifest["tools"])):
        name = cast(str, tool["name"])
        if name in seen:
            path = f"/tools/{index}/name"
            raise ManifestValidationError(
                path, f"Integration manifest has a duplicate tool name at {path}"
            )
        seen.add(name)


def validate_index_document(document: object) -> None:
    """Validate one registry index against the canonical index schema."""
    _validate_schema(document, "index")
