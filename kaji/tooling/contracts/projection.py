"""Stdlib-only projection of canonical contracts for the TypeScript package."""

from __future__ import annotations

import json
from pathlib import Path


PYTHON_LEGACY_CONTRACTS = {
    "tasks/v1/schema.json",
    "tasks/v1/cases/valid.json",
}
PYTHON_LEGACY_EVENT_TYPES = {
    "task.created",
    "task.suspended",
    "task.resumed",
    "task.completed",
    "task.failed",
    "task.cancelled",
}
PYTHON_LEGACY_EVENT_DEFINITIONS = {
    "taskCreated",
    "taskSuspended",
    "taskResumed",
    "taskCompleted",
    "taskFailed",
    "taskCancelled",
}
PYTHON_LEGACY_EXPORTS = {"TaskHandle", "TaskRuntime", "TaskSnapshot", "TaskState", "TaskCompleted"}
TYPESCRIPT_PROJECTED_CONTRACTS = {
    "events/v1/cases/valid.json",
    "events/v1/schema/new.json",
    "events/v1/schema/stored.json",
    "tiers/v1/features.json",
}


def typescript_contract_projection(relative: Path, source: Path) -> bytes:
    """Return the TypeScript package view of a canonical contract."""

    document = json.loads(source.read_text())
    relative_name = relative.as_posix()
    if relative_name == "events/v1/cases/valid.json":
        events = [
            event
            for event in document["events"]
            if event["type"] not in PYTHON_LEGACY_EVENT_TYPES
        ]
        sequences: dict[str, int] = {}
        for event in events:
            session_id = event["session_id"]
            sequences[session_id] = sequences.get(session_id, 0) + 1
            event["sequence"] = sequences[session_id]
        document["events"] = events
    elif relative_name in {"events/v1/schema/new.json", "events/v1/schema/stored.json"}:
        definitions = document["$defs"]
        for name in PYTHON_LEGACY_EVENT_DEFINITIONS:
            definitions.pop(name)
        document["oneOf"] = [
            branch
            for branch in document["oneOf"]
            if branch["$ref"].rsplit("/", 1)[-1] not in PYTHON_LEGACY_EVENT_DEFINITIONS
        ]
    elif relative_name == "tiers/v1/features.json":
        stable = document["publicExports"]["python"]["stable"]
        document["publicExports"]["python"]["stable"] = [
            name for name in stable if name not in PYTHON_LEGACY_EXPORTS
        ]
    return (json.dumps(document, indent=2, ensure_ascii=False) + "\n").encode()
