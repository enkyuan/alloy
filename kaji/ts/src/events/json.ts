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
  return canonicalJsonValue(left) === canonicalJsonValue(right);
}

/** Encode a strict JSON value with the shared ECMAScript number policy. */
export function canonicalJsonValue(value: unknown, subject = "JSON value"): string {
  const ancestors = new WeakSet<object>();

  const assertUnicodeScalarString = (text: string): void => {
    for (let index = 0; index < text.length; index += 1) {
      const unit = text.charCodeAt(index);
      if (unit >= 0xd800 && unit <= 0xdbff) {
        const next = text.charCodeAt(index + 1);
        if (!(next >= 0xdc00 && next <= 0xdfff)) {
          throw new TypeError(`${subject} contains an unpaired Unicode surrogate`);
        }
        index += 1;
      } else if (unit >= 0xdc00 && unit <= 0xdfff) {
        throw new TypeError(`${subject} contains an unpaired Unicode surrogate`);
      }
    }
  };

  const encode = (item: unknown): string => {
    if (item === null) return "null";
    switch (typeof item) {
      case "boolean":
        return item ? "true" : "false";
      case "string":
        assertUnicodeScalarString(item);
        return JSON.stringify(item);
      case "number":
        if (!Number.isFinite(item)) throw new TypeError(`${subject} contains a non-finite number`);
        return Object.is(item, -0) ? "0" : item.toString();
      case "object": {
        if (ancestors.has(item)) throw new TypeError(`${subject} must be acyclic`);
        if (Object.getOwnPropertySymbols(item).length > 0) {
          throw new TypeError(`${subject} JSON object keys must be strings`);
        }
        ancestors.add(item);
        try {
          if (Array.isArray(item)) {
            const descriptors = Object.getOwnPropertyDescriptors(item);
            const values: string[] = [];
            for (let index = 0; index < item.length; index += 1) {
              const descriptor = descriptors[String(index)];
              if (descriptor === undefined || !descriptor.enumerable || !("value" in descriptor)) {
                throw new TypeError(`${subject} array values must be enumerable data values`);
              }
              values.push(encode(descriptor.value));
            }
            for (const key of Object.keys(descriptors)) {
              if (key === "length") continue;
              const index = Number(key);
              if (
                Number.isInteger(index) &&
                index >= 0 &&
                index < item.length &&
                String(index) === key
              ) {
                continue;
              }
              throw new TypeError(`${subject} arrays cannot carry named properties`);
            }
            return `[${values.join(",")}]`;
          }
          const prototype = Object.getPrototypeOf(item);
          if (prototype !== Object.prototype && prototype !== null) {
            throw new TypeError(`${subject} contains a non-plain object`);
          }
          const keys = Object.getOwnPropertyNames(item);
          for (const key of keys) {
            assertUnicodeScalarString(key);
            const descriptor = Object.getOwnPropertyDescriptor(item, key);
            if (descriptor === undefined || !descriptor.enumerable || !("value" in descriptor)) {
              throw new TypeError(
                `${subject} JSON object properties must be enumerable data values`,
              );
            }
          }
          return `{${keys
            .sort()
            .map((key) => {
              const descriptor = Object.getOwnPropertyDescriptor(item, key)!;
              return `${JSON.stringify(key)}:${encode(descriptor.value)}`;
            })
            .join(",")}}`;
        } finally {
          ancestors.delete(item);
        }
      }
      default:
        throw new TypeError(`${subject} contains non-JSON value ${typeof item}`);
    }
  };

  return encode(value);
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
