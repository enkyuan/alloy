import { AsyncLocalStorage } from "node:async_hooks";

interface TransactionMarker {
  active: boolean;
}

export class NestedEventTransactionError extends Error {
  constructor() {
    super("event store session transactions cannot be nested");
    this.name = "NestedEventTransactionError";
  }
}

/** FIFO serialization per key with prompt cleanup after the last waiter. */
export class KeyedSerialExecutor {
  private readonly tails = new Map<string, Promise<void>>();
  private readonly context = new AsyncLocalStorage<TransactionMarker>();

  get activeKeyCount(): number {
    return this.tails.size;
  }

  has(key: string): boolean {
    return this.tails.has(key);
  }

  async run<T>(
    key: string,
    operation: () => Promise<T>,
    afterRelease: () => void = () => undefined,
  ): Promise<T> {
    const inherited = this.context.getStore();
    if (inherited?.active === true) throw new NestedEventTransactionError();

    const previous = this.tails.get(key) ?? Promise.resolve();
    let release!: () => void;
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    const tail = previous.then(() => gate);
    this.tails.set(key, tail);

    await previous;
    const marker: TransactionMarker = { active: true };
    try {
      return await this.context.run(marker, operation);
    } finally {
      marker.active = false;
      release();
      if (this.tails.get(key) === tail) this.tails.delete(key);
      afterRelease();
    }
  }
}
