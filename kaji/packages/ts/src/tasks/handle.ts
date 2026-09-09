import { InMemoryEventCommitter } from "@/events/committer";
import type { EventCommitter } from "@/events/protocols";
import { InMemoryEventStore, type EventStore } from "@/events/store";
import {
  TaskCancelled,
  TaskCreated,
  TaskResumed,
  ToolApprovalApproved,
  ToolApprovalRejected,
  type NewKajiEvent,
  type StoredKajiEvent,
} from "@/events/schemas";
import { systemIdFactory, type IdFactory } from "@/internal/uuid";
import {
  InMemorySessionTurnCoordinator,
  type SessionTurnCoordinator,
} from "@/runtime/session/coordinator";

import { approvalId, projectTask } from "./projector";
import type { PendingApproval, TaskSnapshot } from "./types";

export class TaskNotFoundError extends Error {}

export class InMemoryBackend {
  readonly taskSessions = new Map<string, string>();

  constructor(
    readonly store: EventStore = new InMemoryEventStore(),
    readonly journal: EventCommitter = new InMemoryEventCommitter(store),
    readonly coordinator: SessionTurnCoordinator = new InMemorySessionTurnCoordinator(),
  ) {}
}

export class TaskRuntime {
  constructor(
    private readonly backend: InMemoryBackend,
    private readonly ids: IdFactory = systemIdFactory,
  ) {}

  static forInMemory(options: { ids?: IdFactory } = {}): TaskRuntime {
    return new TaskRuntime(new InMemoryBackend(), options.ids);
  }

  async start(options: {
    session_id: string;
    principal_id: string;
    input: string;
    metadata?: Record<string, unknown>;
    task_id?: string;
  }): Promise<TaskHandle> {
    const taskId = options.task_id ?? this.ids.next("task");
    if (this.backend.taskSessions.has(taskId)) throw new Error(`task already exists: ${taskId}`);
    const handle = TaskHandle.forInMemory(taskId, options.session_id, this.backend, this.ids);
    await this.backend.coordinator.runExclusive(options.session_id, undefined, async () => {
      await this.backend.journal.commit(
        TaskCreated.parse({
          type: "task.created",
          id: this.ids.next("event"),
          task_id: taskId,
          session_id: options.session_id,
          principal_id: options.principal_id,
          input: options.input,
          metadata: options.metadata ?? {},
        }),
      );
      await this.backend.journal.commit(
        TaskResumed.parse({
          type: "task.resumed",
          id: this.ids.next("event"),
          task_id: taskId,
          session_id: options.session_id,
        }),
      );
      this.backend.taskSessions.set(taskId, options.session_id);
    });
    return handle;
  }

  get(taskId: string): TaskHandle {
    const sessionId = this.backend.taskSessions.get(taskId);
    if (!sessionId) throw new TaskNotFoundError(`unknown task: ${taskId}`);
    return TaskHandle.forInMemory(taskId, sessionId, this.backend, this.ids);
  }
}

export class TaskHandle {
  private constructor(
    readonly taskId: string,
    readonly sessionId: string,
    private readonly backend: InMemoryBackend,
    private readonly ids: IdFactory,
  ) {}

  static forInMemory(
    taskId: string,
    sessionId: string,
    backend: InMemoryBackend,
    ids: IdFactory = systemIdFactory,
  ): TaskHandle {
    return new TaskHandle(taskId, sessionId, backend, ids);
  }

  async events(options: { after_sequence?: number } = {}): Promise<readonly StoredKajiEvent[]> {
    return this.backend.store.getEvents(this.sessionId, {
      afterSequence: options.after_sequence ?? 0,
    });
  }

  async snapshot(): Promise<TaskSnapshot> {
    return projectTask(this.taskId, await this.events());
  }

  async pendingApprovals(): Promise<readonly PendingApproval[]> {
    const snapshot = await this.snapshot();
    const pending = new Map<string, PendingApproval>();
    for (const event of await this.events()) {
      if (event.type === "tool.approval.requested") {
        const id = approvalId(event);
        pending.set(id, {
          id,
          capability: event.tool_name,
          risk: event.risk,
          arguments: event.tool_args,
        });
      }
    }
    return snapshot.pending_approvals.map((item) => pending.get(item.id)!).filter(Boolean);
  }

  async cancel(): Promise<TaskSnapshot> {
    return this.append(
      TaskCancelled.parse({
        type: "task.cancelled",
        id: this.ids.next("event"),
        task_id: this.taskId,
        session_id: this.sessionId,
      }),
    );
  }

  async resume(): Promise<TaskSnapshot> {
    return this.append(
      TaskResumed.parse({
        type: "task.resumed",
        id: this.ids.next("event"),
        task_id: this.taskId,
        session_id: this.sessionId,
      }),
    );
  }

  async decideApproval(
    approval: PendingApproval,
    approved: boolean,
    reason = "host decision",
  ): Promise<TaskSnapshot> {
    const [turn_id, tool_call_id] = approval.id.split(":", 2);
    const base = {
      id: this.ids.next("event"),
      session_id: this.sessionId,
      turn_id,
      tool_call_id,
      tool_name: approval.capability,
    };
    return this.append(
      approved
        ? ToolApprovalApproved.parse({ type: "tool.approval.approved", ...base })
        : ToolApprovalRejected.parse({
            type: "tool.approval.rejected",
            ...base,
            error_code: "APPROVAL_REJECTED",
            reason,
          }),
    );
  }

  private async append(event: NewKajiEvent): Promise<TaskSnapshot> {
    return this.backend.coordinator.runExclusive(this.sessionId, undefined, async () => {
      await this.backend.journal.commit(event);
      return projectTask(this.taskId, await this.events());
    });
  }
}
