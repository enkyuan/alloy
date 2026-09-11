"""ArtifactRef validation helpers."""

from typing import Any

from .types import ArtifactRef


def validate_artifact_ref(value: ArtifactRef | dict[str, Any]) -> ArtifactRef:
    return (
        value if isinstance(value, ArtifactRef) else ArtifactRef.model_validate(value)
    )
