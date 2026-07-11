export type DeepReadonly<T> = T extends (...args: never[]) => unknown
  ? T
  : T extends readonly (infer TItem)[]
    ? readonly DeepReadonly<TItem>[]
    : T extends object
      ? { readonly [TKey in keyof T]: DeepReadonly<T[TKey]> }
      : T;

/** Clone a JSON-safe value and freeze every object and array in the clone. */
export function cloneAndFreezeJson<T>(value: T): DeepReadonly<T> {
  return cloneJsonValue(value, new WeakSet()) as DeepReadonly<T>;
}

/** Compare JSON-safe values without depending on object key insertion order. */
export function structurallyEqualJson(left: unknown, right: unknown): boolean {
  return canonicalJson(left, new WeakSet()) === canonicalJson(right, new WeakSet());
}

function cloneJsonValue(value: unknown, ancestors: WeakSet<object>): unknown {
  if (value === null || typeof value === "string" || typeof value === "boolean") return value;
  if (typeof value === "number") {
    if (!Number.isFinite(value)) throw new TypeError("Event values must be JSON-safe");
    return value;
  }
  if (Array.isArray(value)) {
    enter(value, ancestors);
    const clone = value.map((item) => cloneJsonValue(item, ancestors));
    ancestors.delete(value);
    return Object.freeze(clone);
  }
  if (typeof value === "object") {
    assertJsonObject(value);
    enter(value, ancestors);
    const clone: Record<string, unknown> = {};
    for (const [key, child] of Object.entries(value)) {
      Object.defineProperty(clone, key, {
        value: cloneJsonValue(child, ancestors),
        enumerable: true,
        writable: true,
        configurable: true,
      });
    }
    ancestors.delete(value);
    return Object.freeze(clone);
  }
  throw new TypeError("Event values must be JSON-safe");
}

function canonicalJson(value: unknown, ancestors: WeakSet<object>): string {
  if (value === null || typeof value === "string" || typeof value === "boolean") {
    return JSON.stringify(value);
  }
  if (typeof value === "number") {
    if (!Number.isFinite(value)) throw new TypeError("Event values must be JSON-safe");
    return JSON.stringify(value);
  }
  if (Array.isArray(value)) {
    enter(value, ancestors);
    const canonical = `[${value.map((item) => canonicalJson(item, ancestors)).join(",")}]`;
    ancestors.delete(value);
    return canonical;
  }
  if (typeof value === "object") {
    assertJsonObject(value);
    enter(value, ancestors);
    const entries = Object.entries(value as Record<string, unknown>).sort(([left], [right]) =>
      left.localeCompare(right),
    );
    const canonical = `{${entries
      .map(([key, child]) => `${JSON.stringify(key)}:${canonicalJson(child, ancestors)}`)
      .join(",")}}`;
    ancestors.delete(value);
    return canonical;
  }
  throw new TypeError("Event values must be JSON-safe");
}

function assertJsonObject(value: object): void {
  const prototype = Object.getPrototypeOf(value);
  if (
    (prototype !== Object.prototype && prototype !== null) ||
    Object.getOwnPropertySymbols(value).length > 0
  ) {
    throw new TypeError("Event values must be JSON-safe");
  }
}

function enter(value: object, ancestors: WeakSet<object>): void {
  if (ancestors.has(value)) throw new TypeError("Event values must be JSON-safe and acyclic");
  ancestors.add(value);
}
