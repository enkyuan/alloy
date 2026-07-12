"""Cached shared-contract validation for integration manifests and indexes."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from functools import lru_cache
from pathlib import Path
from typing import Any, ClassVar, Literal, cast

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import SchemaError
from jsonschema.protocols import Validator


IntegrationValidationCode = Literal["INTEGRATION_SCHEMA_INVALID"]
SchemaKind = Literal["manifest", "index"]
DRAFT_2020_12 = "https://json-schema.org/draft/2020-12/schema"
_PARAMETER_FORMATS = FormatChecker()
_SINGLE_SUBSCHEMA_KEYS = frozenset(
    {
        "additionalProperties",
        "contains",
        "contentSchema",
        "else",
        "if",
        "items",
        "not",
        "propertyNames",
        "then",
        "unevaluatedItems",
        "unevaluatedProperties",
    }
)
_MAPPING_SUBSCHEMA_KEYS = frozenset(
    {"$defs", "dependentSchemas", "patternProperties", "properties"}
)
_ARRAY_SUBSCHEMA_KEYS = frozenset({"allOf", "anyOf", "oneOf", "prefixItems"})
_PORTABLE_PATTERN_ESCAPES = frozenset(r"\.^$*+?{}[]()|/-")
_PORTABLE_CLASS_ESCAPES = frozenset(r"\[]-^")
_PORTABLE_REPEAT_LIMIT = 9999


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


def _schema_mapping(value: object) -> Mapping[str, object] | None:
    if not isinstance(value, Mapping):
        return None
    return cast(Mapping[str, object], value)


def _is_portable_pattern(pattern: str) -> bool:
    """Validate Kaji's deliberately small Python/ECMAScript regex intersection.

    The subset is printable ASCII literals, capturing groups, alternation,
    ``^``/``$``, ASCII character classes/ranges, greedy quantifiers, and
    escapes of regex punctuation. It excludes ``(?`` extensions, dot,
    shorthand/Unicode classes, backreferences, lazy/possessive quantifiers,
    and non-ASCII syntax so dialect-only constructs fail identically.
    """
    if not pattern or any(not 0x20 <= ord(character) <= 0x7E for character in pattern):
        return False

    index = 0

    def consume_class() -> bool:
        nonlocal index
        index += 1
        if index < len(pattern) and pattern[index] == "^":
            index += 1
        tokens: list[tuple[str, bool, bool]] = []
        while index < len(pattern) and pattern[index] != "]":
            character = pattern[index]
            if character == "[":
                return False
            if character == "\\":
                if (
                    index + 1 >= len(pattern)
                    or pattern[index + 1] not in _PORTABLE_CLASS_ESCAPES
                ):
                    return False
                tokens.append((pattern[index + 1], False, True))
                index += 2
                continue
            tokens.append((character, character == "-", False))
            index += 1
        if index >= len(pattern) or not tokens:
            return False
        index += 1

        for left, right in zip(tokens, tokens[1:], strict=False):
            if (
                not left[2]
                and not right[2]
                and left[0] == right[0]
                and left[0] in "&|~"
            ):
                return False

        cursor = 1 if tokens[0][1] else 0
        while cursor < len(tokens):
            if tokens[cursor][1]:
                if cursor != len(tokens) - 1:
                    return False
                cursor += 1
                continue
            if cursor + 1 < len(tokens) and tokens[cursor + 1][1]:
                if cursor + 1 == len(tokens) - 1:
                    cursor += 2
                    continue
                endpoint = tokens[cursor + 2]
                if endpoint[1] or ord(tokens[cursor][0]) > ord(endpoint[0]):
                    return False
                cursor += 3
                continue
            cursor += 1
        return True

    def consume_quantifier() -> bool:
        nonlocal index
        if index >= len(pattern):
            return True
        if pattern[index] in "*+?":
            index += 1
        elif pattern[index] == "{":
            index += 1
            lower_start = index
            while index < len(pattern) and pattern[index].isdigit():
                index += 1
            lower_text = pattern[lower_start:index]
            if not lower_text or len(lower_text) > 4:
                return False
            lower = int(lower_text)
            upper: int | None = lower
            if index < len(pattern) and pattern[index] == ",":
                index += 1
                upper_start = index
                while index < len(pattern) and pattern[index].isdigit():
                    index += 1
                upper_text = pattern[upper_start:index]
                if len(upper_text) > 4:
                    return False
                upper = int(upper_text) if upper_text else None
            if index >= len(pattern) or pattern[index] != "}":
                return False
            index += 1
            if lower > _PORTABLE_REPEAT_LIMIT or (
                upper is not None and (upper > _PORTABLE_REPEAT_LIMIT or upper < lower)
            ):
                return False
        else:
            return True
        return index >= len(pattern) or pattern[index] not in "*+?{"

    def consume_expression(nested: bool) -> bool:
        nonlocal index
        branch_has_atom = False
        while index < len(pattern):
            character = pattern[index]
            if character == ")":
                return nested and branch_has_atom
            if character == "|":
                if not branch_has_atom:
                    return False
                branch_has_atom = False
                index += 1
                continue
            if character in "*+?{.]}" or character == "}":
                return False
            if character in "^$":
                index += 1
                continue
            if character == "(":
                if index + 1 < len(pattern) and pattern[index + 1] == "?":
                    return False
                index += 1
                if not consume_expression(True) or pattern[index] != ")":
                    return False
                index += 1
            elif character == "[":
                if not consume_class():
                    return False
            elif character == "\\":
                if (
                    index + 1 >= len(pattern)
                    or pattern[index + 1] not in _PORTABLE_PATTERN_ESCAPES
                ):
                    return False
                index += 2
            else:
                index += 1
            branch_has_atom = True
            if not consume_quantifier():
                return False
        return not nested and branch_has_atom

    return consume_expression(False) and index == len(pattern)


def parameter_schema_issue(
    schema: Mapping[str, object], path: tuple[object, ...] = ()
) -> tuple[object, ...] | None:
    """Return the first unsupported path in Kaji's offline Draft 2020-12 subset."""
    dialect = schema.get("$schema")
    if isinstance(dialect, str) and dialect != DRAFT_2020_12:
        return (*path, "$schema")
    identifier = schema.get("$id")
    if isinstance(identifier, str) and not _PARAMETER_FORMATS.conforms(
        identifier, "uri-reference"
    ):
        return (*path, "$id")
    pattern = schema.get("pattern")
    if isinstance(pattern, str) and (
        not _is_portable_pattern(pattern)
        or not _PARAMETER_FORMATS.conforms(pattern, "regex")
    ):
        return (*path, "pattern")

    for keyword in sorted(_SINGLE_SUBSCHEMA_KEYS):
        child = _schema_mapping(schema.get(keyword))
        if child is None:
            continue
        issue = parameter_schema_issue(child, (*path, keyword))
        if issue is not None:
            return issue
    for keyword in sorted(_MAPPING_SUBSCHEMA_KEYS):
        children = _schema_mapping(schema.get(keyword))
        if children is None:
            continue
        for name in sorted(children, key=str):
            child = _schema_mapping(children[name])
            if child is None:
                continue
            issue = parameter_schema_issue(child, (*path, keyword, name))
            if issue is not None:
                return issue
    for keyword in sorted(_ARRAY_SUBSCHEMA_KEYS):
        children = schema.get(keyword)
        if not isinstance(children, list):
            continue
        for index, value in enumerate(children):
            child = _schema_mapping(value)
            if child is None:
                continue
            issue = parameter_schema_issue(child, (*path, keyword, index))
            if issue is not None:
                return issue
    return None


def validate_manifest_document(document: object) -> None:
    """Validate one manifest against the canonical schema and set semantics."""
    _validate_schema(document, "manifest")
    manifest = cast(Mapping[str, Any], document)
    seen: set[str] = set()
    for index, tool in enumerate(cast(list[Mapping[str, Any]], manifest["tools"])):
        parameters = cast(Mapping[str, object], tool["parameters"])
        issue = parameter_schema_issue(parameters)
        if issue is not None:
            suffix = json_pointer(issue)
            path = f"/tools/{index}/parameters{suffix}"
            raise ManifestValidationError(
                path,
                f"Integration manifest has an unsupported parameter schema at {path}",
            )
        try:
            Draft202012Validator.check_schema(parameters)
        except SchemaError as error:
            suffix = json_pointer(error.absolute_path)
            path = f"/tools/{index}/parameters"
            if suffix != "/":
                path += suffix
            raise ManifestValidationError(
                path,
                f"Integration manifest has an invalid parameter schema at {path}",
            ) from error
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
