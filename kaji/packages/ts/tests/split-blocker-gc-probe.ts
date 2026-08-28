import { SplitEventCommitter } from "@/events/committer";
import { SessionPurgeUnsupportedError } from "@/events/errors";
import type { EventBusProtocol } from "@/events/protocols";
import { KajiEvent, type StoredKajiEvent } from "@/events/schemas";
import { beginStoreSessionPurge, registerPurgeBlocker } from "@/events/session-lifecycle";
import { InMemoryEventStore } from "@/events/store";
import { EventType } from "@/events/types";

class RetainedMissingReturnBus implements EventBusProtocol<StoredKajiEvent> {
  activeSubscriptions = 0;
  readonly candidates = new Set<object>();

  async publish(): Promise<void> {}

  subscribe(): AsyncIterableIterator<StoredKajiEvent> {
    this.activeSubscriptions += 1;
    const candidate = {
      next: () => new Promise<IteratorResult<StoredKajiEvent>>(() => undefined),
      [Symbol.asyncIterator]() {
        return this;
      },
    };
    this.candidates.add(candidate);
    return candidate as AsyncIterableIterator<StoredKajiEvent>;
  }

  close(): void {}
}

async function forceCollection(): Promise<void> {
  for (let attempt = 0; attempt < 8; attempt += 1) {
    Bun.gc(true);
    await Bun.sleep(0);
  }
}

function abandonCommitter(
  store: InMemoryEventStore,
  bus: RetainedMissingReturnBus,
): WeakRef<SplitEventCommitter> {
  let committer: SplitEventCommitter | undefined = new SplitEventCommitter(store, bus);
  const reference = new WeakRef(committer);
  try {
    committer.subscribe("gc-poison");
  } catch (error) {
    if (!(error instanceof TypeError)) throw error;
  }
  committer = undefined;
  return reference;
}

async function exercise(): Promise<{
  readonly committerCollected: boolean;
  readonly activeSubscriptions: number;
  readonly purgeBlocked: boolean;
  readonly purged: boolean | null;
}> {
  const store = new InMemoryEventStore();
  await store.append(
    KajiEvent.parse({
      id: "gc-poison",
      type: EventType.USER_MESSAGE,
      session_id: "gc-poison",
      content: "retained",
    }),
  );
  const bus = new RetainedMissingReturnBus();
  const committerReference = abandonCommitter(store, bus);
  await forceCollection();

  let purgeBlocked = false;
  let purged: boolean | null = null;
  try {
    purged = await store.purgeSession("gc-poison");
  } catch (error) {
    if (!(error instanceof SessionPurgeUnsupportedError)) throw error;
    purgeBlocked = true;
  }
  return {
    committerCollected: committerReference.deref() === undefined,
    activeSubscriptions: bus.activeSubscriptions,
    purgeBlocked,
    purged,
  };
}

function abandonStoreWithBlocker(): WeakRef<InMemoryEventStore> {
  let store: InMemoryEventStore | undefined = new InMemoryEventStore();
  const reference = new WeakRef(store);
  registerPurgeBlocker(store, { sessionPurgeComponent: "event_delivery" });
  store = undefined;
  return reference;
}

function unregisterBlockerAndAbandonStore(): {
  readonly blockerRemoved: boolean;
  readonly reference: WeakRef<InMemoryEventStore>;
} {
  let store: InMemoryEventStore | undefined = new InMemoryEventStore();
  const reference = new WeakRef(store);
  const unregister = registerPurgeBlocker(store, {
    sessionPurgeComponent: "event_delivery",
  });
  let initiallyBlocked = false;
  try {
    beginStoreSessionPurge(store, "gc-unregistered");
  } catch (error) {
    if (!(error instanceof SessionPurgeUnsupportedError)) throw error;
    initiallyBlocked = true;
  }
  unregister();
  const lease = beginStoreSessionPurge(store, "gc-unregistered");
  lease.release();
  store = undefined;
  return { blockerRemoved: initiallyBlocked, reference };
}

const outcome = await exercise();
const storeReference = abandonStoreWithBlocker();
const unregistered = unregisterBlockerAndAbandonStore();
await forceCollection();
console.log(
  JSON.stringify({
    ...outcome,
    blockerRemoved: unregistered.blockerRemoved,
    storeCollected: storeReference.deref() === undefined,
    unregisteredStoreCollected: unregistered.reference.deref() === undefined,
  }),
);
