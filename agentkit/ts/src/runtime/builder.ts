/**
 * AgentBuilder: fluent builder for AgentRuntime.
 * Mirrors `agentkit.runtime.agents.builder.AgentBuilder`.
 */
import { AgentRuntime } from "./runtime";
import type { AgentStrategy } from "./runtime";
import type { ModelProvider } from "../providers/base";
import type { ToolPolicy } from "../tools/policy";
import { ToolPlanner, type ApprovalHandler } from "../tools/planner";
import { ToolRegistry } from "../tools/registry";
import type { EventBus } from "../events/bus";
import type { EventStore } from "../events/store";

/** Anything with a register(registry: ToolRegistry) method. */
export interface Integrable {
  register(registry: ToolRegistry): void;
}

export interface AgentBuilderBuildOptions {
  bus: EventBus;
  store: EventStore;
}

export class AgentBuilder {
  private _provider: ModelProvider | undefined;
  private readonly _integrations: Integrable[] = [];
  private _policy: ToolPolicy | undefined;
  private _approvalHandler: ApprovalHandler | undefined;
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

  policy(p: ToolPolicy): this {
    this._policy = p;
    return this;
  }

  approvalHandler(handler: ApprovalHandler): this {
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

  build(opts: AgentBuilderBuildOptions): AgentRuntime {
    if (!this._provider) {
      throw new Error("provider() must be called before build()");
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
      bus: opts.bus,
      store: opts.store,
      systemPrompt: this._systemPrompt,
      strategy: this._strategy,
      tools: registry.listSpecs(),
      policy: this._policy,
      planner,
    });
  }
}
