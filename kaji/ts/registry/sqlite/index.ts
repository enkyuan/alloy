// This is YOUR sqlite integration. Edit it.
// Common customizations:
//   1. Trim the tools array to just what your agent needs
//   2. Restrict exec to specific statement types (e.g., only SELECT)
//   3. Add a transaction helper tool for atomic multi-statement operations
//   4. Map SQLite errors to retry vs surrender for your ToolPlanner policy
// Updates: re-run `kaji add sqlite` to diff against the latest version we ship.
//
// Peer dependency: npm install better-sqlite3 @types/better-sqlite3

import { functionTool } from "@kaji/sdk";
import * as z from "zod";

type Database = {
  prepare: (sql: string) => {
    all: (...params: unknown[]) => unknown[];
    run: (...params: unknown[]) => { changes: number; lastInsertRowid: number | bigint };
  };
};

async function openDb(dbPath: string): Promise<Database> {
  // Dynamic import so better-sqlite3 remains an optional peer dep.
  const mod = (await import("better-sqlite3")) as { default: new (path: string) => Database };
  return new mod.default(dbPath);
}

export function createSqliteIntegration(opts: { dbPath: string }): {
  query: ReturnType<typeof functionTool>;
  exec: ReturnType<typeof functionTool>;
  schema: ReturnType<typeof functionTool>;
} {
  const sqliteQuery = functionTool(
    {
      name: "query",
      namespace: "sqlite",
      description: "Run a SELECT query and return rows.",
      parameters: z.object({
        sql: z.string(),
        params: z.array(z.unknown()).optional(),
      }),
      risk: "read",
    },
    async ({ sql, params }) => {
      const db = await openDb(opts.dbPath);
      const rows = db.prepare(sql).all(...(params ?? []));
      return { rows, rowCount: rows.length };
    },
  );

  const sqliteExec = functionTool(
    {
      name: "exec",
      namespace: "sqlite",
      description: "Execute a SQL statement (INSERT/UPDATE/DELETE/DDL).",
      parameters: z.object({
        sql: z.string(),
        params: z.array(z.unknown()).optional(),
      }),
      risk: "write",
    },
    async ({ sql, params }) => {
      const db = await openDb(opts.dbPath);
      const info = db.prepare(sql).run(...(params ?? []));
      return { changes: info.changes, lastInsertRowid: info.lastInsertRowid };
    },
  );

  const sqliteSchema = functionTool(
    {
      name: "schema",
      namespace: "sqlite",
      description: "List CREATE TABLE statements for all tables.",
      parameters: z.object({}),
      risk: "read",
    },
    async () => {
      const db = await openDb(opts.dbPath);
      const rows = db
        .prepare(
          "SELECT name, sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name",
        )
        .all() as { name: string; sql: string }[];
      return { tables: rows.map(({ name, sql }) => ({ name, sql })) };
    },
  );

  return { query: sqliteQuery, exec: sqliteExec, schema: sqliteSchema };
}
