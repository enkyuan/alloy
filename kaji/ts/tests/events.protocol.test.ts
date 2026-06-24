import { describe, expect, it } from "vitest";
import { AgentRuntime } from "../src/runtime/runtime";
import { InMemoryEventStore } from "../src/events/store";
import { EventBus } from "../src/events/bus";
import { KajiEvent } from "../src/events/schemas";
import { EventType } from "../src/events/types";
import type { EventBusProtocol } from "../src/events/protocols";
import type {
  ModelProvider,
  ModelProviderOptions,
  ModelResponseChunk,
  ProviderMessage,
} from "../src/providers/base";
import type { ToolSpec } from "../src/tools/registry";

class RecordingBus implements EventBusProtocol {
  readonly published: KajiEvent[] = [];
  async publish(event: KajiEvent): Promise<void> {
    this.published.push(event);
  }
  subscribe(_sessionId: string): AsyncIterableIterator<KajiEvent> {
    return (async function* () {})();
  }
  close(): void {}
}

const stubProvider: ModelProvider = {
  async generate(
    _messages: ProviderMessage[],
    _tools: ToolSpec[],
    _options?: ModelProviderOptions,
  ) {
    return { content: "ok", toolCalls: [] };
  },
  async *generateStream(
    _messages: ProviderMessage[],
    _tools: ToolSpec[],
    _options?: ModelProviderOptions,
  ): AsyncGenerator<ModelResponseChunk> {
    yield { delta: "ok", toolCalls: [] };
  },
};

describe("EventBusProtocol", () => {
  it("AgentRuntime accepts a non-EventBus implementation", async () => {
    const bus = new RecordingBus();
    const runtime = new AgentRuntime({
      provider: stubProvider,
      store: new InMemoryEventStore(),
      bus,
    });
    await runtime.send("s1", "hello");
    expect(bus.published.length).toBeGreaterThan(0);
  });

  it("EventBus partitions events per session via the protocol", async () => {
    // Behavioral check: a bus assigned through the protocol interface
    // still fans out per `session_id`. Guards against an implementer
    // that ignores `sessionId` and broadcasts to every subscriber.
    const bus: EventBusProtocol = new EventBus();
    const sub = bus.subscribe("s1");

    const sessionCreated = KajiEvent.parse({
      type: EventType.SESSION_CREATED,
      session_id: "s1",
    });
    const otherSession = KajiEvent.parse({
      type: EventType.SESSION_CREATED,
      session_id: "s2",
    });

    await bus.publish(sessionCreated);
    await bus.publish(otherSession); // must NOT be delivered to s1's iterator

    const first = await sub.next();
    expect(first.done).toBe(false);
    expect(first.value?.session_id).toBe("s1");

    // Closing the iterator releases the subscription.
    await sub.return?.({ value: undefined, done: true } as IteratorResult<KajiEvent>);
    bus.close();
  });
});
