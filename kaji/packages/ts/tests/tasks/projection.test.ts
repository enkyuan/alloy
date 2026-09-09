import {
  ArtifactEmitted,
  TaskCompleted,
  ToolApprovalApproved,
  ToolApprovalRequested,
  ToolCallFailed,
} from "@/events/schemas";
import { artifact } from "@/artifacts/types";
import { InMemoryBackend, TaskRuntime, TaskState } from "@/tasks";
import { describe, expect, it } from "vitest";

async function task() {
  const backend = new InMemoryBackend();
  const handle = await new TaskRuntime(backend).start({
    session_id: "session",
    principal_id: "principal",
    input: "hello",
    task_id: "task",
  });
  return { backend, handle };
}

describe("task projection", () => {
  it("projects lifecycle and event cursor from the journal", async () => {
    const { backend, handle } = await task();
    expect((await handle.snapshot()).state).toBe(TaskState.RUNNING);
    await backend.journal.commit(
      TaskCompleted.parse({
        type: "task.completed",
        id: "complete",
        task_id: "task",
        session_id: "session",
      }),
    );
    expect(await handle.snapshot()).toMatchObject({
      state: TaskState.COMPLETED,
      sequence_cursor: 3,
    });
    expect((await handle.events({ after_sequence: 1 })).map((event) => event.sequence)).toEqual([
      2, 3,
    ]);
  });

  it("uses canonical approval and unknown-outcome events", async () => {
    const { backend, handle } = await task();
    await backend.journal.commit(
      ToolApprovalRequested.parse({
        type: "tool.approval.requested",
        id: "approval",
        session_id: "session",
        turn_id: "turn",
        tool_name: "write",
        tool_call_id: "call",
        tool_args: { raw: true },
        risk: "write",
      }),
    );
    expect((await handle.snapshot()).state).toBe(TaskState.WAITING_FOR_APPROVAL);
    expect((await handle.snapshot()).pending_approvals[0]).not.toHaveProperty("arguments");
    await backend.journal.commit(
      ToolApprovalApproved.parse({
        type: "tool.approval.approved",
        id: "approved",
        session_id: "session",
        turn_id: "turn",
        tool_name: "write",
        tool_call_id: "call",
      }),
    );
    await backend.journal.commit(
      ArtifactEmitted.parse({
        type: "artifact.emitted",
        id: "artifact",
        session_id: "session",
        turn_id: "turn",
        tool_call_id: "call",
        artifact: artifact("first", "text/plain", "memory:first"),
      }),
    );
    await backend.journal.commit(
      ToolCallFailed.parse({
        type: "tool.call.failed",
        id: "unknown",
        session_id: "session",
        turn_id: "turn",
        tool_name: "write",
        tool_call_id: "call",
        error: "unknown",
        outcome: "unknown",
      }),
    );
    expect(await handle.snapshot()).toMatchObject({
      state: TaskState.RECONCILIATION_REQUIRED,
      artifacts: [{ id: "first" }],
    });
  });
});
