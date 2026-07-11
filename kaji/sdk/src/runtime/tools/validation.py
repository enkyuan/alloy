"""Compiled Draft 2020-12 validation for provider-supplied tool arguments."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import SchemaError
from jsonschema.protocols import Validator

from kaji.runtime.tools.errors import (
    ToolArgumentValidationError,
    ToolSchemaValidationError,
    json_pointer,
)


class ToolSchemaSpec(Protocol):
    """Structural input needed to compile a tool schema without import cycles."""

    @property
    def parameters(self) -> dict[str, Any]: ...


class ToolSchemaValidator:
    """Compile each tool schema once and validate calls without mutating input."""

    def __init__(self, specs: Mapping[str, ToolSchemaSpec]) -> None:
        self._validators: dict[str, Validator] = {}
        for name, spec in specs.items():
            try:
                Draft202012Validator.check_schema(spec.parameters)
            except SchemaError as error:
                raise ToolSchemaValidationError.from_jsonschema(name, error) from None
            self._validators[name] = Draft202012Validator(
                spec.parameters,
                format_checker=FormatChecker(),
            )

    def validate(self, tool_name: str, arguments: object) -> None:
        validator = self._validators.get(tool_name)
        if validator is None:
            return
        errors = sorted(
            validator.iter_errors(arguments),
            key=lambda error: (
                json_pointer(error.absolute_path),
                json_pointer(error.absolute_schema_path),
            ),
        )
        if errors:
            raise ToolArgumentValidationError.from_jsonschema(tool_name, errors[0])
