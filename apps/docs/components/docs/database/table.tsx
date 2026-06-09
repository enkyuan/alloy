"use client";

import { startTransition, useState } from "react";
import { DynamicCodeBlock } from "@components/ui/dynamic-code-block";
import type { DBFieldAttribute, DBSchema, DefaultDialects } from "@lib/copy-schema";
import { copySchema } from "@lib/copy-schema";
import { drizzleResolver } from "@lib/copy-schema/adapter/drizzle";
import { prismaResolver } from "@lib/copy-schema/adapter/prisma";
import { cn } from "@lib/utils";
import { Key, Link as LinkIcon } from "lucide-react";
import { TypeIcon } from "./type-icon";

// ─── Types ────────────────────────────────────────────────────────────────────

interface Field {
  name: string;
  type: string;
  description: string;
  isPrimaryKey?: boolean;
  isForeignKey?: boolean;
  isOptional?: boolean;
  isUnique?: boolean;
  references?: {
    model: string;
    field: string;
    onDelete?: "no action" | "restrict" | "cascade" | "set null" | "set default";
  };
}

const typeAliases: Record<string, string> = {
  text: "string",
  integer: "number",
  int: "number",
  bigint: "number",
  float: "number",
  double: "number",
  decimal: "number",
  bool: "boolean",
  object: "json",
  timestamp: "date",
  datetime: "date",
};

type ViewMode = "table" | "sql" | "prisma" | "drizzle";
type SQLDialect = DefaultDialects;
type DrizzleProvider = "pg" | "mysql" | "sqlite";

// ─── Helpers ──────────────────────────────────────────────────────────────────

function fieldToDBField(field: Field): DBFieldAttribute {
  const t = field.type.toLowerCase();
  const isArray = t.endsWith("[]");
  const raw = isArray ? t.slice(0, -2) : t;
  const aliased = typeAliases[raw] ?? raw;
  const type = (
    isArray && (aliased === "string" || aliased === "number")
      ? `${aliased}[]`
      : isArray
        ? t
        : aliased
  ) as DBFieldAttribute["type"];
  const bigint = raw === "bigint";

  let references: DBFieldAttribute["references"] | undefined;
  if (field.isForeignKey && field.references) {
    references = {
      model: field.references.model,
      field: field.references.field,
      onDelete: field.references.onDelete ?? "cascade",
    };
  }

  return {
    fieldName: field.name,
    type,
    required: field.isPrimaryKey ? true : !field.isOptional,
    references,
    unique: field.isUnique ?? false,
    bigint,
  };
}

function generateSchema(
  tableName: string,
  fields: Field[],
  view: ViewMode,
  sqlDialect: SQLDialect,
  drizzleProvider: DrizzleProvider,
): string {
  const schema: DBSchema<false> = {
    modelName: tableName,
    fields: fields.map(fieldToDBField),
  };

  if (view === "sql") {
    return copySchema(schema, { dialect: sqlDialect, mode: "create" }).result;
  }
  if (view === "prisma") {
    return copySchema(schema, {
      dialect: prismaResolver({}),
      mode: "create",
    }).result;
  }
  if (view === "drizzle") {
    return copySchema(schema, {
      dialect: drizzleResolver({ provider: drizzleProvider }),
      mode: "create",
    }).result;
  }
  return "";
}

function SchemaCodeBlock({ code, lang }: { code: string; lang: string }) {
  return (
    <div className="[&_figure]:my-0 [&_figure]:border-0 [&_figure]:rounded-none [&_pre]:text-[13px]">
      <DynamicCodeBlock code={code} lang={lang} allowCopy />
    </div>
  );
}

const sqlDialects: { key: SQLDialect; label: string }[] = [
  { key: "postgresql", label: "PostgreSQL" },
  { key: "mysql", label: "MySQL" },
  { key: "sqlite", label: "SQLite" },
  { key: "mssql", label: "MSSQL" },
];

const drizzleProviders: { key: DrizzleProvider; label: string }[] = [
  { key: "pg", label: "PostgreSQL" },
  { key: "mysql", label: "MySQL" },
  { key: "sqlite", label: "SQLite" },
];

// ─── DatabaseTable ─────────────────────────────────────────────────────────────

export function DatabaseTable({ fields, name }: { fields: Field[]; name?: string }) {
  const [view, setView] = useState<ViewMode>("table");
  const [sqlDialect, setSqlDialect] = useState<SQLDialect>("postgresql");
  const [drizzleProvider, setDrizzleProvider] = useState<DrizzleProvider>("pg");
  const tableName = name || "table";

  return (
    <div className="my-4 border shadow-sm overflow-hidden dark:bg-[#030303]">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-2 border-b">
        <div className="flex items-center gap-2">
          <svg
            xmlns="http://www.w3.org/2000/svg"
            width="14"
            height="14"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
            className="text-foreground/60"
          >
            <ellipse cx="12" cy="5" rx="9" ry="3" />
            <path d="M3 5v14a9 3 0 0 0 18 0V5" />
            <path d="M3 12a9 3 0 0 0 18 0" />
          </svg>
          <span className="text-[11px] leading-0 text-foreground/60 font-mono font-medium uppercase tracking-wider">
            Table
          </span>
        </div>
        <div className="flex items-center">
          {(
            [
              { key: "table", label: "Table" },
              { key: "sql", label: "SQL" },
              { key: "prisma", label: "Prisma" },
              { key: "drizzle", label: "Drizzle" },
            ] as const
          ).map((opt) => (
            <button
              key={opt.key}
              type="button"
              onClick={() => startTransition(() => setView(opt.key))}
              className={cn(
                "relative px-2 py-0.5 font-mono text-xs font-medium transition-colors cursor-pointer",
                view === opt.key
                  ? "text-foreground/80"
                  : "text-foreground/40 hover:text-foreground/60",
              )}
            >
              {opt.label}
              {view === opt.key && (
                <span className="absolute inset-x-2 -bottom-2 h-[1.5px] bg-foreground/80" />
              )}
            </button>
          ))}
        </div>
      </div>

      {/* Sub-selector for SQL dialect or Drizzle provider */}
      {view === "sql" && (
        <div className="flex items-center px-4 py-1 border-b">
          {sqlDialects.map((d) => (
            <button
              key={d.key}
              type="button"
              onClick={() => startTransition(() => setSqlDialect(d.key))}
              className={cn(
                "relative px-1.5 py-1 font-mono text-xs font-medium transition-colors cursor-pointer",
                sqlDialect === d.key
                  ? "text-foreground/80"
                  : "text-foreground/40 hover:text-foreground/60",
              )}
            >
              {d.label}
              {sqlDialect === d.key && (
                <span className="absolute inset-x-1.5 -bottom-1 h-[1.5px] bg-foreground/80" />
              )}
            </button>
          ))}
        </div>
      )}
      {view === "drizzle" && (
        <div className="flex items-center px-4 py-1 border-b">
          {drizzleProviders.map((d) => (
            <button
              key={d.key}
              type="button"
              onClick={() => startTransition(() => setDrizzleProvider(d.key))}
              className={cn(
                "relative px-1.5 py-1 font-mono text-xs font-medium transition-colors cursor-pointer",
                drizzleProvider === d.key
                  ? "text-foreground/80"
                  : "text-foreground/40 hover:text-foreground/60",
              )}
            >
              {d.label}
              {drizzleProvider === d.key && (
                <span className="absolute inset-x-1.5 -bottom-1 h-[1.5px] bg-foreground/80" />
              )}
            </button>
          ))}
        </div>
      )}

      {view === "table" ? (
        <div className="overflow-x-auto">
          {/* Column headers */}
          <div className="grid grid-cols-[minmax(160px,1.2fr)_minmax(100px,0.8fr)_minmax(40px,0.4fr)_minmax(150px,2fr)] min-w-[600px] border-b bg-foreground/2">
            {["Field", "Type", "Key", "Description"].map((label) => (
              <div
                key={label}
                className="px-4 py-1 text-[11px] font-mono font-medium uppercase tracking-wider text-foreground/60"
              >
                {label}
              </div>
            ))}
          </div>

          {/* Rows */}
          {fields.map((field) => (
            <div
              key={field.name}
              className="grid grid-cols-[minmax(160px,1.2fr)_minmax(100px,0.8fr)_minmax(40px,0.4fr)_minmax(150px,2fr)] min-w-[600px] items-center border-b border-dashed border-foreground/10 last:border-b-0 hover:bg-foreground/[0.02] transition-colors"
            >
              <div className="px-4 py-2 font-mono text-[13px] text-foreground/80 break-all">
                {field.name}
                {field.isOptional && (
                  <span
                    title="Optional"
                    aria-label="Optional"
                    className="text-foreground/40 text-[11px] font-medium select-none"
                  >
                    {" ?"}
                  </span>
                )}
              </div>
              <div className="px-4 py-2 flex items-center gap-1.5">
                <TypeIcon type={field.type} />
                <span className="font-mono text-[13px] text-foreground/80">{field.type}</span>
              </div>
              <div className="px-4 py-2">
                {field.isPrimaryKey && (
                  <span className="inline-flex items-center gap-1 font-mono text-[13px] text-amber-600 dark:text-amber-500 uppercase">
                    <Key className="size-2.5" />
                    PK
                  </span>
                )}
                {field.isForeignKey && (
                  <span className="inline-flex items-center gap-1 font-mono text-[13px] text-blue-600 dark:text-blue-400 uppercase">
                    <LinkIcon className="size-2.5" />
                    FK
                  </span>
                )}
                {!field.isPrimaryKey && !field.isForeignKey && (
                  <span className="text-foreground/20 uppercase">-</span>
                )}
              </div>
              <div className="px-4 py-2 text-[13px] text-foreground/70 leading-relaxed">
                {field.description}
              </div>
            </div>
          ))}
        </div>
      ) : (
        <SchemaCodeBlock
          code={generateSchema(tableName, fields, view, sqlDialect, drizzleProvider)}
          lang={view === "sql" ? "sql" : view === "prisma" ? "prisma" : "typescript"}
        />
      )}
    </div>
  );
}
