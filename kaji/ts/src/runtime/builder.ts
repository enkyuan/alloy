/**
 * AgentBuilder: fluent builder for AgentRuntime.
 * Mirrors `kaji.runtime.agents.builder.AgentBuilder`.
 */
import { AgentRuntime } from "@/runtime/runtime";
import type { AgentStrategy } from "@/runtime/runtime";
import type { ModelProvider } from "@/providers/base";
import type { ToolPolicy } from "@/tools/policy";
import { ToolPlanner, type AnyApprovalHandler } from "@/tools/planner";
import { ToolRegistry } from "@/tools/registry";
import type { EventBusProtocol, EventCommitter } from "@/events/protocols";
import { InMemoryEventCommitter, SplitEventCommitter } from "@/events/committer";
import { InMemoryEventStore, type EventStore } from "@/events/store";

/** Anything with a register(registry: ToolRegistry) method. */
export interface Integrable {
  register(registry: ToolRegistry): void;
}

export interface AgentBuilderBuildOptions {
  /** Canonical append + subscription boundary. */
  committer?: EventCommitter;
  /** @deprecated Supplying a bus opts into the experimental split adapter. */
  bus?: EventBusProtocol;
  /** Defaults to the injected committer's store, otherwise a fresh in-memory store. */
  store?: EventStore;
}

export class AgentBuilder {
  private _provider: ModelProvider | undefined;
  private readonly _integrations: Integrable[] = [];
  private _policy: ToolPolicy | undefined;
  private _approvalHandler: AnyApprovalHandler | undefined;
  private _systemPrompt = "You are a helpful assistant.";
  private _strategy: AgentStrategy | undefined;

  provider(p: ModelProvider): this {
    this._provider = p;
    return this;
  }

  integration(i: Integrable): this {
    this._integrations.push(i);
    return this;
  }

  /** Add a function-level tool created by `functionTool({...}, handler)`. */
  tool(bound: Integrable): this {
    this._integrations.push(bound);
    return this;
  }

  policy(p: ToolPolicy): this {
    this._policy = p;
    return this;
  }

  approvalHandler(handler: AnyApprovalHandler): this {
    this._approvalHandler = handler;
    return this;
  }

  systemPrompt(prompt: string): this {
    this._systemPrompt = prompt;
    return this;
  }

  strategy(s: AgentStrategy): this {
    this._strategy = s;
    return this;
  }

  build(opts: AgentBuilderBuildOptions = {}): AgentRuntime {
    if (!this._provider) {
      throw new Error("provider() must be called before build()");
    }
    let store: EventStore;
    let committer: EventCommitter;
    if (opts.committer !== undefined) {
      if (opts.store !== undefined && opts.store !== opts.committer.store) {
        throw new Error("AgentBuilder store must match the injected committer store");
      }
      store = opts.committer.store;
      committer = opts.committer;
    } else {
      store = opts.store ?? new InMemoryEventStore();
      committer =
        opts.bus !== undefined
          ? new SplitEventCommitter(store, opts.bus)
          : new InMemoryEventCommitter(store);
    }

    const registry = new ToolRegistry();
    for (const integration of this._integrations) {
      integration.register(registry);
    }

    const specs = new Map(
      registry.listSpecs({ enabledOnly: false }).map((spec) => [spec.name, spec]),
    );
    const planner = new ToolPlanner({
      executor: (name, args) => registry.execute("builder", name, args),
      policy: this._policy,
      approvalHandler: this._approvalHandler,
      specs,
    });

    return new AgentRuntime({
      provider: this._provider,
      store,
      committer,
      systemPrompt: this._systemPrompt,
      strategy: this._strategy,
      tools: registry.listSpecs(),
      policy: this._policy,
      planner,
    });
  }
}
