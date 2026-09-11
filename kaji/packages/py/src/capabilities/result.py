"""Validated output from a Capability execution."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

from kaji.artifacts import ArtifactRef, validate_artifact_ref
from kaji.events.errors import MAX_DURABLE_TOOL_RESULT_BYTES
from kaji.events.json import JsonValue, durable_json_snapshot


@dataclass(frozen=True)
class CapabilityResult:
    value: JsonValue | None = None
    artifacts: tuple[ArtifactRef, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "value",
            durable_json_snapshot(
                self.value,
                subject="tool_result",
                max_bytes=MAX_DURABLE_TOOL_RESULT_BYTES,
            ),
        )
        artifacts = tuple(validate_artifact_ref(item) for item in self.artifacts)
        ids = [item.id for item in artifacts]
        if len(ids) != len(set(ids)):
            raise ValueError("artifact ids must be unique within a capability result")
        object.__setattr__(self, "artifacts", artifacts)

    def to_tool_result(self) -> JsonValue:
        """Serialize this validated result for the existing tool execution path."""

        return durable_json_snapshot(
            {
                "value": self.value,
                "artifacts": [
                    artifact.model_dump(mode="json", exclude_none=True)
                    for artifact in self.artifacts
                ],
            },
            subject="tool_result",
            max_bytes=MAX_DURABLE_TOOL_RESULT_BYTES,
        )


def capability_result(
    value: JsonValue | None = None,
    artifacts: Sequence[ArtifactRef | dict[str, Any]] = (),
) -> CapabilityResult:
    return CapabilityResult(
        value=value,
        artifacts=tuple(validate_artifact_ref(item) for item in artifacts),
    )
