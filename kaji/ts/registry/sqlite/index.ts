// This is YOUR sqlite integration. Edit it.
// Common customizations:
//   1. Trim the tools array to just what your agent needs
//   2. Narrow the explicit exec statement policy
//   3. Adjust row and busy-timeout limits for your workload
//   4. Map driver errors to retry vs surrender for your ToolPlanner policy
// Updates: re-run `kaji add sqlite` to diff against the latest version we ship.
//
// Peer dependency: npm install better-sqlite3 @types/better-sqlite3

import { functionTool } from "@kaji/sdk";
import * as z from "zod";

const DEFAULT_BUSY_TIMEOUT_MS = 5_000;
const DEFAULT_MAX_ROWS = 1_000;
const DEFAULT_MAX_SCHEMA_ROWS = 1_000;

export interface SqliteStatement {
  readonly readonly: boolean;
  readonly reader: boolean;
  iterate(...params: unknown[]): Iterable<unknown>;
  run(...params: unknown[]): { changes: number; lastInsertRowid: number | bigint };
}

export interface SqliteDatabase {
  prepare(sql: string): SqliteStatement;
  pragma(source: string): unknown;
  close(): void;
}

export type SqliteDatabaseFactory = (dbPath: string) => SqliteDatabase | Promise<SqliteDatabase>;

export type SqliteExecClass =
  | "insert"
  | "update"
  | "delete"
  | "replace"
  | "create"
  | "alter"
  | "drop";

export interface SqliteExecPolicy {
  readonly allowedStatements: readonly SqliteExecClass[];
}

export interface SqliteIntegrationOptions {
  readonly dbPath: string;
  readonly databaseFactory?: SqliteDatabaseFactory;
  readonly busyTimeoutMs?: number;
  readonly maxRows?: number;
  readonly maxSchemaRows?: number;
  readonly execPolicy?: SqliteExecPolicy;
}

export interface SqliteIntegration {
  readonly query: ReturnType<typeof functionTool>;
  readonly exec: ReturnType<typeof functionTool>;
  readonly schema: ReturnType<typeof functionTool>;
  close(): Promise<void>;
}

const EXEC_CLASSES = new Set<SqliteExecClass>([
  "insert",
  "update",
  "delete",
  "replace",
  "create",
  "alter",
  "drop",
]);

const FORBIDDEN_SQL = new Set([
  "attach",
  "begin",
  "commit",
  "detach",
  "end",
  "pragma",
  "release",
  "rollback",
  "savepoint",
  "vacuum",
]);

function positiveLimit(value: number | undefined, fallback: number, name: string): number {
  const result = value ?? fallback;
  if (!Number.isSafeInteger(result) || result < 1) {
    throw new RangeError(`${name} must be a positive safe integer`);
  }
  return result;
}

function skipComment(sql: string, index: number): number | undefined {
  if (sql.startsWith("--", index)) {
    const newline = sql.indexOf("\n", index + 2);
    return newline === -1 ? sql.length : newline + 1;
  }
  if (sql.startsWith("/*", index)) {
    const end = sql.indexOf("*/", index + 2);
    if (end === -1) throw new Error("SQL contains an unterminated comment");
    return end + 2;
  }
  return undefined;
}

function trailingIsOnlyComments(sql: string, start: number): boolean {
  let index = start;
  while (index < sql.length) {
    if (/\s/.test(sql[index]!)) {
      index++;
      continue;
    }
    const next = skipComment(sql, index);
    if (next === undefined) return false;
    index = next;
  }
  return true;
}

function singleStatement(sql: string): string {
  if (typeof sql !== "string") throw new TypeError("SQL must be a string");
  let quote: "'" | '"' | "`" | "]" | undefined;
  for (let index = 0; index < sql.length; index++) {
    const char = sql[index]!;
    if (quote !== undefined) {
      if (char === quote) {
        if (quote !== "]" && sql[index + 1] === quote) index++;
        else quote = undefined;
      }
      continue;
    }
    const commentEnd = skipComment(sql, index);
    if (commentEnd !== undefined) {
      index = commentEnd - 1;
      continue;
    }
    if (char === "'" || char === '"' || char === "`") {
      quote = char;
      continue;
    }
    if (char === "[") {
      quote = "]";
      continue;
    }
    if (char === ";") {
      if (!trailingIsOnlyComments(sql, index + 1)) {
        throw new Error("SQLite integration accepts exactly one statement");
      }
      const statement = sql.slice(0, index).trim();
      if (statement.length === 0) throw new Error("SQL statement must not be empty");
      return statement;
    }
  }
  if (quote !== undefined) throw new Error("SQL contains an unterminated quoted value");
  const statement = sql.trim();
  if (statement.length === 0 || trailingIsOnlyComments(statement, 0)) {
    throw new Error("SQL statement must not be empty");
  }
  return statement;
}

function sqlTokens(sql: string): string[] {
  const tokens: string[] = [];
  let quote: "'" | '"' | "`" | "]" | undefined;
  for (let index = 0; index < sql.length; index++) {
    const char = sql[index]!;
    if (quote !== undefined) {
      if (char === quote) {
        if (quote !== "]" && sql[index + 1] === quote) index++;
        else quote = undefined;
      }
      continue;
    }
    const commentEnd = skipComment(sql, index);
    if (commentEnd !== undefined) {
      index = commentEnd - 1;
      continue;
    }
    if (char === "'" || char === '"' || char === "`") {
      quote = char;
      continue;
    }
    if (char === "[") {
      quote = "]";
      continue;
    }
    if (/[A-Za-z_]/.test(char)) {
      let end = index + 1;
      while (end < sql.length && /[A-Za-z0-9_]/.test(sql[end]!)) end++;
      tokens.push(sql.slice(index, end).toLowerCase());
      index = end - 1;
    }
  }
  return tokens;
}

function nextSqlContent(sql: string, start: number): number {
  let index = start;
  while (index < sql.length) {
    if (/\s/.test(sql[index]!)) {
      index++;
      continue;
    }
    const commentEnd = skipComment(sql, index);
    if (commentEnd === undefined) return index;
    index = commentEnd;
  }
  return index;
}

function containsQuotedLoadExtensionCall(sql: string): boolean {
  for (let index = 0; index < sql.length; index++) {
    const commentEnd = skipComment(sql, index);
    if (commentEnd !== undefined) {
      index = commentEnd - 1;
      continue;
    }
    const opening = sql[index]!;
    if (opening !== "'" && opening !== '"' && opening !== "`" && opening !== "[") continue;
    const closing = opening === "[" ? "]" : opening;
    let value = "";
    let cursor = index + 1;
    let closed = false;
    while (cursor < sql.length) {
      const char = sql[cursor]!;
      if (char === closing) {
        if (closing !== "]" && sql[cursor + 1] === closing) {
          value += closing;
          cursor += 2;
          continue;
        }
        closed = true;
        break;
      }
      value += char;
      cursor++;
    }
    if (!closed) return false; // singleStatement reports the stable syntax error.
    if (
      opening !== "'" &&
      value.toLowerCase() === "load_extension" &&
      sql[nextSqlContent(sql, cursor + 1)] === "("
    ) {
      return true;
    }
    index = cursor;
  }
  return false;
}

function assertSafeQueryShape(statement: string): void {
  const tokens = sqlTokens(statement);
  const first = tokens[0];
  if (first === undefined) throw new Error("SQL statement must contain a keyword");
  if (
    FORBIDDEN_SQL.has(first) ||
    tokens.includes("load_extension") ||
    containsQuotedLoadExtensionCall(statement)
  ) {
    throw new Error(`SQLite query rejects prohibited statement class ${first}`);
  }
}

function execClass(statement: string): SqliteExecClass {
  const tokens = sqlTokens(statement);
  const first = tokens[0];
  if (first === undefined) throw new Error("SQL statement must contain a keyword");
  if (
    FORBIDDEN_SQL.has(first) ||
    tokens.includes("load_extension") ||
    containsQuotedLoadExtensionCall(statement)
  ) {
    throw new Error(`SQLite exec rejects prohibited statement class ${first}`);
  }
  if (!EXEC_CLASSES.has(first as SqliteExecClass)) {
    throw new Error(`SQLite exec rejects unknown statement class ${first}`);
  }
  return first as SqliteExecClass;
}

function allowedExecClasses(policy: SqliteExecPolicy | undefined): ReadonlySet<SqliteExecClass> {
  if (policy === undefined) return new Set();
  if (!Array.isArray(policy.allowedStatements)) {
    throw new TypeError("execPolicy.allowedStatements must be an array");
  }
  const classes = new Set<SqliteExecClass>();
  for (const statementClass of policy.allowedStatements) {
    if (!EXEC_CLASSES.has(statementClass)) {
      throw new TypeError(`Unknown SQLite exec statement class ${JSON.stringify(statementClass)}`);
    }
    classes.add(statementClass);
  }
  return classes;
}

function boundedRows(
  statement: SqliteStatement,
  params: readonly unknown[],
  maxRows: number,
): {
  rows: unknown[];
  truncated: boolean;
} {
  const rows: unknown[] = [];
  const iterator = statement.iterate(...params)[Symbol.iterator]();
  let returned = false;
  const closeIterator = () => {
    if (returned) return;
    returned = true;
    iterator.return?.();
  };
  try {
    for (let index = 0; index <= maxRows; index++) {
      const next = iterator.next();
      if (next.done) return { rows, truncated: false };
      if (index === maxRows) {
        closeIterator();
        return { rows, truncated: true };
      }
      rows.push(next.value);
    }
  } catch (error) {
    closeIterator();
    throw error;
  }
  return { rows, truncated: false };
}

function jsonSafeRowId(value: number | bigint): number | string {
  if (typeof value === "number") return value;
  const asNumber = Number(value);
  return Number.isSafeInteger(asNumber) ? asNumber : value.toString();
}

const defaultDatabaseFactory: SqliteDatabaseFactory = async (dbPath) => {
  const packageName = "better-sqlite3";
  const module = (await import(packageName)) as {
    default: new (path: string) => SqliteDatabase;
  };
  return new module.default(dbPath);
};

export function createSqliteIntegration(options: SqliteIntegrationOptions): SqliteIntegration {
  if (typeof options?.dbPath !== "string" || options.dbPath.trim().length === 0) {
    throw new TypeError("SQLite dbPath is required");
  }
  const busyTimeoutMs = positiveLimit(
    options.busyTimeoutMs,
    DEFAULT_BUSY_TIMEOUT_MS,
    "busyTimeoutMs",
  );
  const maxRows = positiveLimit(options.maxRows, DEFAULT_MAX_ROWS, "maxRows");
  const maxSchemaRows = positiveLimit(
    options.maxSchemaRows,
    DEFAULT_MAX_SCHEMA_ROWS,
    "maxSchemaRows",
  );
  const allowedExec = allowedExecClasses(options.execPolicy);
  const factory = options.databaseFactory ?? defaultDatabaseFactory;
  let closed = false;
  let databasePromise: Promise<SqliteDatabase> | undefined;
  let closePromise: Promise<void> | undefined;

  const database = async (): Promise<SqliteDatabase> => {
    if (closed) throw new Error("SQLite integration is closed");
    if (databasePromise === undefined) {
      const opening = Promise.resolve()
        .then(() => factory(options.dbPath))
        .then(async (db) => {
          if (closed) {
            db.close();
            throw new Error("SQLite integration is closed");
          }
          try {
            db.pragma(`busy_timeout = ${busyTimeoutMs}`);
          } catch (error) {
            try {
              db.close();
            } catch {
              // Preserve the setup error that made this connection unusable.
            }
            throw error;
          }
          return db;
        });
      databasePromise = opening;
      void opening.catch(() => {
        if (databasePromise === opening && !closed) databasePromise = undefined;
      });
    }
    return databasePromise;
  };

  const sqliteQuery = functionTool(
    {
      name: "query",
      namespace: "sqlite",
      description: "Run one bounded read-only row-producing SQLite statement.",
      parameters: z.object({
        sql: z.string(),
        params: z.array(z.unknown()).optional(),
      }),
      risk: "read",
    },
    async ({ sql, params }) => {
      const source = singleStatement(sql);
      assertSafeQueryShape(source);
      const statement = (await database()).prepare(source);
      if (statement.readonly !== true || statement.reader !== true) {
        throw new Error("SQLite query requires a read-only row-producing statement");
      }
      const { rows, truncated } = boundedRows(statement, params ?? [], maxRows);
      return { rows, rowCount: rows.length, truncated };
    },
  );

  const sqliteExec = functionTool(
    {
      name: "exec",
      namespace: "sqlite",
      description: "Execute one explicitly allowed destructive SQLite statement.",
      parameters: z.object({
        sql: z.string(),
        params: z.array(z.unknown()).optional(),
      }),
      risk: "destructive",
    },
    async ({ sql, params }) => {
      const source = singleStatement(sql);
      const statementClass = execClass(source);
      if (!allowedExec.has(statementClass)) {
        throw new Error(`SQLite exec statement class ${statementClass} is not explicitly allowed`);
      }
      const statement = (await database()).prepare(source);
      if (statement.reader || statement.readonly) {
        throw new Error("SQLite exec requires destructive non-row-producing driver metadata");
      }
      const info = statement.run(...(params ?? []));
      return {
        changes: info.changes,
        lastInsertRowid: jsonSafeRowId(info.lastInsertRowid),
      };
    },
  );

  const sqliteSchema = functionTool(
    {
      name: "schema",
      namespace: "sqlite",
      description: "List bounded CREATE TABLE metadata for application tables.",
      parameters: z.object({}),
      risk: "read",
    },
    async () => {
      const statement = (await database()).prepare(
        "SELECT name, sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name",
      );
      if (statement.readonly !== true || statement.reader !== true) {
        throw new Error("SQLite schema query must be read-only and row-producing");
      }
      const { rows, truncated } = boundedRows(statement, [], maxSchemaRows);
      const tables = rows.map((row, index) => {
        if (typeof row !== "object" || row === null || Array.isArray(row)) {
          throw new Error(`SQLite schema row ${index} is not an object`);
        }
        const { name, sql } = row as Record<string, unknown>;
        if (typeof name !== "string" || typeof sql !== "string") {
          throw new Error(`SQLite schema row ${index} has an invalid shape`);
        }
        return { name, sql };
      });
      return { tables, truncated };
    },
  );

  const close = (): Promise<void> => {
    if (closePromise !== undefined) return closePromise;
    closed = true;
    const pending = databasePromise;
    closePromise = (async () => {
      if (pending === undefined) return;
      let db: SqliteDatabase;
      try {
        db = await pending;
      } catch {
        return;
      }
      db.close();
    })();
    return closePromise;
  };

  return { query: sqliteQuery, exec: sqliteExec, schema: sqliteSchema, close };
}
