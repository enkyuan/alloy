"""Normalized failures raised while validating tool schemas and arguments."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any, ClassVar, Literal

from jsonschema.exceptions import SchemaError, ValidationError

ToolValidationCode = Literal["INVALID_TOOL_SCHEMA", "INVALID_TOOL_ARGUMENTS"]


def json_pointer(path: Iterable[object]) -> str:
    """Render a jsonschema path as the JSON Pointer used by shared contracts."""
    parts = list(path)
    if not parts:
        return "/"
    escaped = (str(part).replace("~", "~0").replace("/", "~1") for part in parts)
    return "/" + "/".join(escaped)


def _bounded_message(subject: str, keyword: object, path: str) -> str:
    # jsonschema's own message includes the rejected value. Public failures must
    # describe the violated rule without reflecting provider arguments.
    message = f"{subject} failed {str(keyword)} validation at {path}"
    return message if len(message) <= 200 else message[:199] + "…"


class ToolValidationError(ValueError):
    """Base class carrying the cross-SDK normalized validation shape."""

    code: ClassVar[ToolValidationCode]

    def __init__(self, tool_name: str, path: str, message: str) -> None:
        self.tool_name = tool_name
        self.path = path
        self.message = message
        self.retryable = False
        self.outcome: Literal["not_started"] = "not_started"
        super().__init__(message)

    def normalized(self) -> dict[str, str]:
        """Return the stable public validation object."""
        return {"code": self.code, "path": self.path, "message": self.message}


class ToolArgumentValidationError(ToolValidationError):
    """Raised when provider arguments do not satisfy a compiled tool schema."""

    code: ClassVar[Literal["INVALID_TOOL_ARGUMENTS"]] = "INVALID_TOOL_ARGUMENTS"

    @classmethod
    def from_jsonschema(
        cls, tool_name: str, error: ValidationError
    ) -> ToolArgumentValidationError:
        path = json_pointer(error.absolute_path)
        return cls(
            tool_name,
            path,
            _bounded_message("Tool arguments", error.validator, path),
        )

    @classmethod
    def non_object(cls, tool_name: str) -> ToolArgumentValidationError:
        return cls(
            tool_name,
            "/",
            "Invalid tool arguments: arguments must be an object",
        )

    @classmethod
    def parse_error(cls, tool_name: str) -> ToolArgumentValidationError:
        return cls(
            tool_name,
            "/",
            "Invalid tool arguments: arguments were not valid JSON",
        )


class ToolSchemaValidationError(ToolValidationError):
    """Raised when a tool definition is not valid Draft 2020-12 JSON Schema."""

    code: ClassVar[Literal["INVALID_TOOL_SCHEMA"]] = "INVALID_TOOL_SCHEMA"

    @classmethod
    def from_jsonschema(
        cls, tool_name: str, error: SchemaError
    ) -> ToolSchemaValidationError:
        path = json_pointer(error.absolute_path)
        return cls(
            tool_name,
            path,
            _bounded_message("Tool schema", error.validator, path),
        )


def validation_failure_fields(error: ToolValidationError) -> dict[str, Any]:
    """Return additive event/result fields for a normalized validation failure."""
    return {
        "error_code": error.code,
        "error_path": error.path,
        "retryable": error.retryable,
        "outcome": error.outcome,
    }
