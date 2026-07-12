"""Fresh-process RSS probe for the projection-owned context index."""

from __future__ import annotations

import gc
import json
import resource
import sys

from kaji.infra.events.replay import SessionState, apply_event
from kaji.infra.events.schemas import (
    AgentMessageCompleted,
    AgentReasoningStarted,
    KajiEvent,
    ToolCallCompleted,
    ToolCallRequested,
    UserMessage,
    require_stored_event,
)
from kaji.runtime.sessions.projector import SessionProjector


def _events(batch: int) -> tuple[KajiEvent, ...]:
    call_id = f"call-{batch}"
    return (
        UserMessage(session_id="rss", content=str(batch)),
        AgentReasoningStarted(session_id="rss"),
        ToolCallRequested(
            session_id="rss",
            turn_id=f"turn-{batch}",
            tool_name="lookup",
            tool_call_id=call_id,
            tool_args={"batch": batch},
        ),
        ToolCallCompleted(
            session_id="rss",
            turn_id=f"turn-{batch}",
            tool_name="lookup",
            tool_call_id=call_id,
            result={"ok": True},
        ),
        AgentMessageCompleted(session_id="rss", content=f"done-{batch}"),
    )


def _rss_bytes() -> int:
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(rss if sys.platform == "darwin" else rss * 1024)


def main() -> None:
    mode = sys.argv[1]
    projector = SessionProjector("rss") if mode == "indexed" else None
    state = SessionState(session_id="rss") if projector is None else None
    sequence = 0
    for batch in range(2_000):
        for event in _events(batch):
            sequence += 1
            stored = require_stored_event(
                event.model_copy(update={"sequence": sequence})
            )
            if projector is None:
                assert state is not None
                apply_event(state, stored)
            else:
                projector.apply(stored)
    projected = state if projector is None else projector.state
    assert projected is not None
    gc.collect()
    print(json.dumps({"rss": _rss_bytes(), "messages": len(projected.messages)}))


if __name__ == "__main__":
    main()
