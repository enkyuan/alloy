import { afterEach, beforeEach, describe, expect, it } from "vitest";

describe("event id default with no Web Crypto", () => {
  const originalCrypto = (globalThis as { crypto?: unknown }).crypto;

  beforeEach(() => {
    delete (globalThis as { crypto?: unknown }).crypto;
  });

  afterEach(() => {
    if (originalCrypto === undefined) {
      delete (globalThis as { crypto?: unknown }).crypto;
    } else {
      (globalThis as { crypto?: unknown }).crypto = originalCrypto;
    }
  });

  it("constructs an event when globalThis.crypto is undefined", async () => {
    expect((globalThis as { crypto?: unknown }).crypto).toBeUndefined();

    const { KajiEvent } = await import("@/events/schemas");
    const { EventType } = await import("@/events/types");

    const event = KajiEvent.parse({
      type: EventType.SESSION_CREATED,
      session_id: "s1",
    });

    expect(event.id).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/);
  });
});
