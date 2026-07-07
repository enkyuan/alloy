## Task 2: Port OpenAPI Generator Parity Into `apps/cli gen`

**Purpose:** `apps/cli gen` is currently path-param-only, while the Python generator already handles query params, operation/path-item params, primitive types, and body filtering. This makes generated tools incomplete for real integrations.

**Modify:**

- `apps/cli/src/commands/gen.ts`
- `apps/cli/test/commands/gen.test.ts`

**Reference:**

- `kaji/sdk/src/cli/gen.py`
- `kaji/sdk/tests/cli/test_gen.py`

**Implementation requirements:**

- Parse path-item-level parameters and operation-level parameters.
- Operation-level params override path-item-level params by `(in, name)`.
- Preserve fallback extraction for `{path}` template params when OpenAPI metadata omits them.
- Support `path` and `query` params in both TS and Python generated handlers.
- Include primitive schema types in generated parameter schemas when available:
  - `string`
  - `integer`
  - `number`
  - `boolean`
- Include descriptions from OpenAPI parameter descriptions when present.
- Required arrays should include required path/query params only.
- For GET/HEAD/OPTIONS, do not emit a request body.
- For write methods, generate body JSON from args excluding path/query params.
- Surface HTTP failures:
  - TS: check `r.ok` and throw an error containing status and response text.
  - Python: call `r.raise_for_status()`.

**Parser shape:**

```ts
interface OpenApiParameter {
  name: string;
  in: "path" | "query" | string;
  required?: boolean;
  description?: string;
  schema?: { type?: string };
}

interface ParamInfo {
  name: string;
  location: "path" | "query";
  required: boolean;
  type: "string" | "integer" | "number" | "boolean";
  description: string;
}

function parseParameters(
  path: string,
  pathItemParams: OpenApiParameter[] | undefined,
  operationParams: OpenApiParameter[] | undefined,
): ParamInfo[] {
  const byKey = new Map<string, ParamInfo>();
  for (const p of [...(pathItemParams ?? []), ...(operationParams ?? [])]) {
    if (p.in !== "path" && p.in !== "query") continue;
    const location = p.in;
    const type = normalizePrimitiveType(p.schema?.type);
    byKey.set(`${location}:${p.name}`, {
      name: p.name,
      location,
      required: location === "path" || p.required === true,
      type,
      description: p.description ?? `${p.name} ${location} parameter`,
    });
  }
  for (const name of extractPathParams(path)) {
    const key = `path:${name}`;
    if (!byKey.has(key)) {
      byKey.set(key, {
        name,
        location: "path",
        required: true,
        type: "string",
        description: `${name} path parameter`,
      });
    }
  }
  return [...byKey.values()];
}
```

**Generated TS handler target:**

```ts
export async function get_pet(args: Record<string, unknown>): Promise<unknown> {
  const url = new URL(`${BASE_URL}/pets/${args.id}`);
  if (args.includeDetails !== undefined) {
    url.searchParams.set("includeDetails", String(args.includeDetails));
  }
  const r = await fetch(url.toString(), {
    method: "GET",
    headers: { Authorization: `Bearer ${API_KEY}` },
  });
  if (!r.ok) {
    throw new Error(`GET ${url.pathname} failed: ${r.status} ${await r.text()}`);
  }
  return r.json();
}
```

**Generated Python handler target:**

```py
async def get_pet(args: dict) -> dict:
    url = f"{BASE_URL}/pets/{args['id']}"
    params = {}
    if args.get("includeDetails") is not None:
        params["includeDetails"] = args["includeDetails"]
    async with httpx.AsyncClient() as c:
        r = await c.request("GET", url, params=params, headers={"Authorization": f"Bearer {API_KEY}"})
        r.raise_for_status()
        return r.json()
```

**Tests:**

- GET path param remains required.
- GET query param is included in ToolSpec/TOOLS schema and emitted through `url.searchParams.set` or Python `params`.
- Path-item-level params merge into operations.
- Operation-level params override path-item params.
- GET output does not contain `body: JSON.stringify`.
- POST output excludes path/query params from body JSON.
- TS generated code includes `if (!r.ok)`.
- Python generated code includes `r.raise_for_status()`.

**Verify:**

```bash
cd apps/cli
bun run test -- test/commands/gen.test.ts
bun run typecheck
```

**Checkpoint:** `fix(cli): generate complete openapi tool params`

