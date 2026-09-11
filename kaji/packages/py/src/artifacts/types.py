"""Immutable, bounded references to host-native execution outputs."""

from __future__ import annotations

import re
from typing import Any

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    field_validator,
    model_validator,
)

_NAMESPACED_TYPE = re.compile(r"^[^/\s]+/[^/\s]+$")
_URI_WITH_SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")


class ArtifactRef(BaseModel):
    id: str
    type: str
    uri: str
    version: str | None = Field(default=None, exclude_if=lambda value: value is None)
    media_type: str | None = Field(default=None, exclude_if=lambda value: value is None)
    metadata: dict[str, JsonValue] | None = Field(
        default=None, exclude_if=lambda value: value is None
    )

    model_config = ConfigDict(extra="forbid", frozen=True)

    @field_validator("id", "version", "media_type")
    @classmethod
    def _non_empty(cls, value: str | None) -> str | None:
        if value is not None and not value:
            raise ValueError("must not be empty")
        return value

    @field_validator("type")
    @classmethod
    def _namespaced_type(cls, value: str) -> str:
        if _NAMESPACED_TYPE.fullmatch(value) is None:
            raise ValueError("must be a non-empty namespaced type")
        return value

    @field_validator("uri")
    @classmethod
    def _uri_with_scheme(cls, value: str) -> str:
        if _URI_WITH_SCHEME.match(value) is None:
            raise ValueError("must have a URI scheme")
        return value

    @field_validator("metadata", mode="before")
    @classmethod
    def _durable_metadata(cls, value: Any) -> Any:
        if value is None:
            return value
        if not isinstance(value, dict):
            raise ValueError("must be a JSON object")
        from kaji.events.errors import (
            MAX_DURABLE_TOOL_RESULT_BYTES,
            DurableJsonLimitError,
            InvalidDurableValueError,
        )
        from kaji.events.json import durable_json_snapshot

        try:
            return durable_json_snapshot(
                value,
                subject="artifact_ref",
                max_bytes=MAX_DURABLE_TOOL_RESULT_BYTES,
            )
        except (DurableJsonLimitError, InvalidDurableValueError) as exc:
            raise ValueError("must be bounded durable JSON") from exc

    @model_validator(mode="after")
    def _bounded_ref(self) -> "ArtifactRef":
        from kaji.events.errors import MAX_DURABLE_TOOL_RESULT_BYTES
        from kaji.events.json import durable_json_snapshot

        durable_json_snapshot(
            self.model_dump(mode="python", exclude_none=True),
            subject="artifact_ref",
            max_bytes=MAX_DURABLE_TOOL_RESULT_BYTES,
        )
        return self


def artifact(
    id: str,
    type: str,
    uri: str,
    *,
    version: str | None = None,
    media_type: str | None = None,
    metadata: dict[str, JsonValue] | None = None,
) -> ArtifactRef:
    return ArtifactRef(
        id=id,
        type=type,
        uri=uri,
        version=version,
        media_type=media_type,
        metadata=metadata,
    )
