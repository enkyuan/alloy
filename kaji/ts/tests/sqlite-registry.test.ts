import { describe, expect, it, vi } from "vitest";

import type { ToolExecutionContext } from "@/index";
import {
  createSqliteIntegration,
  type SqliteDatabase,
  type SqliteDatabaseFactory,
  type SqliteStatement,
} from "../registry/sqlite/index";

const ctx: ToolExecutionContext = {
  principalId: "tester",
  sessionId: "session",
  turnId: "turn",
  requestId: "request",
  traceId: "trace",
  toolCallId: "call",
  idempotencyKey: "session:call",
  signal: new AbortController().signal,
  metadata: {},
};

function statement(
  options: {
    readonly?: boolean;
    reader?: boolean;
    rows?: readonly unknown[];
    run?: { changes: number; lastInsertRowid: number | bigint };
  } = {},
): SqliteStatement & { iterate: ReturnType<typeof vi.fn>; run: ReturnType<typeof vi.fn> } {
  const rows = options.rows ?? [];
  return {
    readonly: options.readonly ?? true,
    reader: options.reader ?? true,
    iterate: vi.fn(() => rows.values()),
    run: vi.fn(() => options.run ?? { changes: 1, lastInsertRowid: 1 }),
  };
}

function database(
  prepareImpl: (sql: string) => SqliteStatement = () => statement(),
): SqliteDatabase & {
  prepare: ReturnType<typeof vi.fn>;
  pragma: ReturnType<typeof vi.fn>;
  close: ReturnType<typeof vi.fn>;
} {
  return {
    prepare: vi.fn<(sql: string) => SqliteStatement>(prepareImpl),
    pragma: vi.fn<(source: string) => unknown>(() => undefined),
    close: vi.fn<() => void>(() => undefined),
  };
}

function factory(db: SqliteDatabase): SqliteDatabaseFactory & ReturnType<typeof vi.fn> {
  return vi.fn(async () => db);
}

describe("sqlite registry connection lifecycle", () => {
  it("opens lazily once across concurrent first use and configures busy timeout once", async () => {
    const db = database((sql) =>
      statement(
        sql.includes("sqlite_master")
          ? { rows: [{ name: "items", sql: "CREATE TABLE items(id)" }] }
          : { rows: [{ value: 1 }] },
      ),
    );
    const open = factory(db);
    const tools = createSqliteIntegration({
      dbPath: "test.sqlite",
      databaseFactory: open,
      busyTimeoutMs: 321,
    });

    expect(open).not.toHaveBeenCalled();
    const [query, schema] = await Promise.all([
      tools.query.handler({ sql: "SELECT 1" }, ctx),
      tools.schema.handler({}, ctx),
    ]);
    expect(query).toMatchObject({ rows: [{ value: 1 }], truncated: false });
    expect(schema).toMatchObject({
      tables: [{ name: "items", sql: "CREATE TABLE items(id)" }],
      truncated: false,
    });
    expect(open).toHaveBeenCalledOnce();
    expect(open).toHaveBeenCalledWith("test.sqlite");
    expect(db.pragma).toHaveBeenCalledOnce();
    expect(db.pragma).toHaveBeenCalledWith("busy_timeout = 321");
  });

  it("closes terminally and idempotently, then rejects every tool", async () => {
    const db = database(() => statement({ rows: [{ value: 1 }] }));
    const tools = createSqliteIntegration({ dbPath: "test.sqlite", databaseFactory: factory(db) });
    await tools.query.handler({ sql: "SELECT 1" }, ctx);
    const first = tools.close();
    const second = tools.close();
    expect(second).toBe(first);
    await Promise.all([first, second]);
    expect(db.close).toHaveBeenCalledOnce();
    await expect(tools.query.handler({ sql: "SELECT 1" }, ctx)).rejects.toThrow(/closed/);
    await expect(tools.exec.handler({ sql: "INSERT INTO t VALUES (1)" }, ctx)).rejects.toThrow(
      /not explicitly allowed|closed/,
    );
    await expect(tools.schema.handler({}, ctx)).rejects.toThrow(/closed/);
  });

  it("does not open when closed before first use", async () => {
    const db = database();
    const open = factory(db);
    const tools = createSqliteIntegration({ dbPath: "test.sqlite", databaseFactory: open });
    await tools.close();
    expect(open).not.toHaveBeenCalled();
    await expect(tools.query.handler({ sql: "SELECT 1" }, ctx)).rejects.toThrow(/closed/);
  });

  it("clears a failed open so the next call can retry", async () => {
    const db = database(() => statement({ rows: [{ recovered: true }] }));
    const openError = new Error("native open failed");
    const open = vi
      .fn<SqliteDatabaseFactory>()
      .mockRejectedValueOnce(openError)
      .mockResolvedValueOnce(db);
    const tools = createSqliteIntegration({ dbPath: "test.sqlite", databaseFactory: open });

    await expect(tools.query.handler({ sql: "SELECT 1" }, ctx)).rejects.toBe(openError);
    await expect(tools.query.handler({ sql: "SELECT 1" }, ctx)).resolves.toMatchObject({
      rows: [{ recovered: true }],
    });
    expect(open).toHaveBeenCalledTimes(2);
    expect(db.pragma).toHaveBeenCalledOnce();
  });
});

describe("sqlite registry query classification and row bounds", () => {
  it("accepts comments, one trailing semicolon, and semicolons inside strings", async () => {
    const db = database(() => statement({ rows: [{ value: ";" }] }));
    const tools = createSqliteIntegration({ dbPath: "test.sqlite", databaseFactory: factory(db) });

    await expect(
      tools.query.handler({ sql: "-- comment\nSELECT ';' AS value; /* trailing */" }, ctx),
    ).resolves.toMatchObject({ rows: [{ value: ";" }] });
    expect(db.prepare).toHaveBeenCalledOnce();
  });

  it("rejects multiple statements before preparing", async () => {
    const db = database();
    const tools = createSqliteIntegration({ dbPath: "test.sqlite", databaseFactory: factory(db) });
    await expect(tools.query.handler({ sql: "SELECT 1; -- gap\n SELECT 2" }, ctx)).rejects.toThrow(
      /exactly one statement/,
    );
    expect(db.prepare).not.toHaveBeenCalled();
  });

  it.each([
    "PRAGMA table_info(items)",
    "ATTACH DATABASE 'other.db' AS other",
    "BEGIN",
    "SELECT load_extension('evil')",
  ])("rejects prohibited query shape %s before preparing", async (sql) => {
    const db = database();
    const tools = createSqliteIntegration({ dbPath: "test.sqlite", databaseFactory: factory(db) });
    await expect(tools.query.handler({ sql }, ctx)).rejects.toThrow(/prohibited/);
    expect(db.prepare).not.toHaveBeenCalled();
  });

  it.each([
    `SELECT "load_extension"('evil')`,
    "SELECT `load_extension`('evil')",
    "SELECT [load_extension]('evil')",
  ])("rejects quoted load_extension query calls: %s", async (sql) => {
    const db = database();
    const tools = createSqliteIntegration({ dbPath: "test.sqlite", databaseFactory: factory(db) });
    await expect(tools.query.handler({ sql }, ctx)).rejects.toThrow(/prohibited/);
    expect(db.prepare).not.toHaveBeenCalled();
  });

  it("does not treat load_extension text in strings or comments as a call", async () => {
    const db = database(() => statement({ rows: [{ safe: true }] }));
    const tools = createSqliteIntegration({ dbPath: "test.sqlite", databaseFactory: factory(db) });
    await expect(
      tools.query.handler(
        { sql: `SELECT '"load_extension"()' AS value /* [load_extension]() */` },
        ctx,
      ),
    ).resolves.toMatchObject({ rows: [{ safe: true }] });
    expect(db.prepare).toHaveBeenCalledOnce();
  });

  it("accepts a read-only CTE but rejects a row-producing CTE mutation", async () => {
    const read = statement({ readonly: true, reader: true, rows: [{ value: 1 }] });
    const mutation = statement({ readonly: false, reader: true, rows: [{ id: 1 }] });
    const db = database((sql) => (sql.includes("DELETE") ? mutation : read));
    const tools = createSqliteIntegration({ dbPath: "test.sqlite", databaseFactory: factory(db) });

    await expect(
      tools.query.handler({ sql: "WITH value AS (SELECT 1) SELECT * FROM value" }, ctx),
    ).resolves.toMatchObject({ rows: [{ value: 1 }] });
    await expect(
      tools.query.handler(
        { sql: "WITH gone AS (DELETE FROM t RETURNING id) SELECT * FROM gone" },
        ctx,
      ),
    ).rejects.toThrow(/read-only row-producing/);
  });

  it.each([
    { readonly: false, reader: true },
    { readonly: true, reader: false },
    { readonly: false, reader: false },
  ])("requires driver metadata to be both readonly and reader: %o", async (metadata) => {
    const db = database(() => statement(metadata));
    const tools = createSqliteIntegration({ dbPath: "test.sqlite", databaseFactory: factory(db) });
    await expect(tools.query.handler({ sql: "SELECT 1" }, ctx)).rejects.toThrow(
      /read-only row-producing/,
    );
  });

  it("iterates only maxRows + 1 without materializing all rows", async () => {
    let pulls = 0;
    let closes = 0;
    const bounded: SqliteStatement = {
      readonly: true,
      reader: true,
      iterate: () => ({
        *[Symbol.iterator]() {
          try {
            for (const row of [{ id: 1 }, { id: 2 }, { id: 3 }, { id: 4 }]) {
              pulls++;
              yield row;
            }
          } finally {
            closes++;
          }
        },
      }),
      run: () => ({ changes: 0, lastInsertRowid: 0 }),
    };
    const db = database(() => bounded);
    const tools = createSqliteIntegration({
      dbPath: "test.sqlite",
      databaseFactory: factory(db),
      maxRows: 2,
    });
    await expect(tools.query.handler({ sql: "SELECT id FROM items" }, ctx)).resolves.toEqual({
      rows: [{ id: 1 }, { id: 2 }],
      rowCount: 2,
      truncated: true,
    });
    expect(pulls).toBe(3);
    expect(closes).toBe(1);
    expect("all" in bounded).toBe(false);
  });
});

describe("sqlite registry destructive exec policy", () => {
  it("is destructive and requires an explicit closed statement class", async () => {
    const db = database(() => statement({ readonly: false, reader: false }));
    const tools = createSqliteIntegration({ dbPath: "test.sqlite", databaseFactory: factory(db) });
    expect(tools.exec.spec.risk).toBe("destructive");
    await expect(tools.exec.handler({ sql: "INSERT INTO items VALUES (1)" }, ctx)).rejects.toThrow(
      /not explicitly allowed/,
    );
    expect(db.prepare).not.toHaveBeenCalled();
  });

  it("allows only configured classes and prepares exactly once", async () => {
    const prepared = statement({
      readonly: false,
      reader: false,
      run: { changes: 1, lastInsertRowid: 7 },
    });
    const db = database(() => prepared);
    const tools = createSqliteIntegration({
      dbPath: "test.sqlite",
      databaseFactory: factory(db),
      execPolicy: { allowedStatements: ["insert"] },
    });
    await expect(
      tools.exec.handler({ sql: "INSERT INTO items(value) VALUES (?)", params: ["x"] }, ctx),
    ).resolves.toEqual({ changes: 1, lastInsertRowid: 7 });
    expect(db.prepare).toHaveBeenCalledOnce();
    expect(prepared.run).toHaveBeenCalledWith("x");

    await expect(tools.exec.handler({ sql: "UPDATE items SET value = 'y'" }, ctx)).rejects.toThrow(
      /not explicitly allowed/,
    );
    expect(db.prepare).toHaveBeenCalledOnce();
  });

  it.each([
    `INSERT INTO items(value) VALUES ("load_extension"('evil'))`,
    "INSERT INTO items(value) VALUES (`load_extension`('evil'))",
    "INSERT INTO items(value) VALUES ([load_extension]('evil'))",
  ])("rejects quoted load_extension calls in an allowed exec class: %s", async (sql) => {
    const db = database(() => statement({ readonly: false, reader: false }));
    const tools = createSqliteIntegration({
      dbPath: "test.sqlite",
      databaseFactory: factory(db),
      execPolicy: { allowedStatements: ["insert"] },
    });
    await expect(tools.exec.handler({ sql }, ctx)).rejects.toThrow(/prohibited/);
    expect(db.prepare).not.toHaveBeenCalled();
  });

  it("allows load_extension text in exec strings and comments", async () => {
    const db = database(() => statement({ readonly: false, reader: false }));
    const tools = createSqliteIntegration({
      dbPath: "test.sqlite",
      databaseFactory: factory(db),
      execPolicy: { allowedStatements: ["insert"] },
    });
    await expect(
      tools.exec.handler(
        {
          sql: `INSERT INTO items(value) VALUES ('[load_extension]()') /* "load_extension"() */`,
        },
        ctx,
      ),
    ).resolves.toMatchObject({ changes: 1 });
    expect(db.prepare).toHaveBeenCalledOnce();
  });

  it.each([
    "BEGIN",
    "COMMIT",
    "ATTACH DATABASE 'other.db' AS other",
    "DETACH DATABASE other",
    "PRAGMA journal_mode=WAL",
    "SELECT load_extension('evil')",
    "WITH changed AS (DELETE FROM t RETURNING id) SELECT * FROM changed",
    "INSERT INTO t VALUES (1); DELETE FROM t",
  ])("rejects prohibited, unknown, or multi-statement exec: %s", async (sql) => {
    const db = database();
    const tools = createSqliteIntegration({
      dbPath: "test.sqlite",
      databaseFactory: factory(db),
      execPolicy: { allowedStatements: ["insert", "delete"] },
    });
    await expect(tools.exec.handler({ sql }, ctx)).rejects.toThrow();
    expect(db.prepare).not.toHaveBeenCalled();
  });

  it("converts unsafe bigint row IDs to JSON-safe strings", async () => {
    const prepared = statement({
      readonly: false,
      reader: false,
      run: { changes: 1, lastInsertRowid: 9_007_199_254_740_993n },
    });
    const tools = createSqliteIntegration({
      dbPath: "test.sqlite",
      databaseFactory: factory(database(() => prepared)),
      execPolicy: { allowedStatements: ["insert"] },
    });
    await expect(
      tools.exec.handler({ sql: "INSERT INTO items DEFAULT VALUES" }, ctx),
    ).resolves.toEqual({ changes: 1, lastInsertRowid: "9007199254740993" });
  });
});

describe("sqlite registry schema and driver errors", () => {
  it("bounds schema iteration and validates row shape", async () => {
    const db = database(() =>
      statement({
        rows: [
          { name: "a", sql: "CREATE TABLE a(id)" },
          { name: "b", sql: "CREATE TABLE b(id)" },
        ],
      }),
    );
    const tools = createSqliteIntegration({
      dbPath: "test.sqlite",
      databaseFactory: factory(db),
      maxSchemaRows: 1,
    });
    await expect(tools.schema.handler({}, ctx)).resolves.toEqual({
      tables: [{ name: "a", sql: "CREATE TABLE a(id)" }],
      truncated: true,
    });
  });

  it("surfaces driver errors without replacing their identity", async () => {
    const driverError = new Error("database is locked");
    const db = database(() => {
      throw driverError;
    });
    const tools = createSqliteIntegration({ dbPath: "test.sqlite", databaseFactory: factory(db) });
    await expect(tools.query.handler({ sql: "SELECT 1" }, ctx)).rejects.toBe(driverError);
  });
});
