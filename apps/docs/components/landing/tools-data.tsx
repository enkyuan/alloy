import type { ReactNode } from "react";

// Tool-category glyphs for the tools showcase. Keyed by tool category, not provider brand.
export const toolIcons: Record<string, () => ReactNode> = {
  Function: () => (
    <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24">
      <path
        fill="none"
        stroke="currentColor"
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth="2"
        d="M4 21q1 0 1.5-.5T6 18.5V8a4 4 0 0 1 4-4M9 13h6"
      />
    </svg>
  ),
  Http: () => (
    <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24">
      <path
        fill="none"
        stroke="currentColor"
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth="2"
        d="M12 21a9 9 0 1 0 0-18a9 9 0 0 0 0 18M3 12h18M12 3a14 14 0 0 1 0 18a14 14 0 0 1 0-18"
      />
    </svg>
  ),
  Database: () => (
    <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24">
      <path
        fill="none"
        stroke="currentColor"
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth="2"
        d="M12 8c4.418 0 8-1.343 8-3s-3.582-3-8-3s-8 1.343-8 3s3.582 3 8 3M4 5v6c0 1.657 3.582 3 8 3s8-1.343 8-3V5M4 11v6c0 1.657 3.582 3 8 3s8-1.343 8-3v-6"
      />
    </svg>
  ),
  Search: () => (
    <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24">
      <path
        fill="none"
        stroke="currentColor"
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth="2"
        d="m21 21l-4.35-4.35M11 18a7 7 0 1 0 0-14a7 7 0 0 0 0 14"
      />
    </svg>
  ),
  File: () => (
    <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24">
      <path
        fill="none"
        stroke="currentColor"
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth="2"
        d="M14.5 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7.5L14.5 2zM14 2v6h6"
      />
    </svg>
  ),
  Code: () => (
    <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24">
      <path
        fill="none"
        stroke="currentColor"
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth="2"
        d="m16 18l6-6l-6-6M8 6l-6 6l6 6"
      />
    </svg>
  ),
  Mcp: () => (
    <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24">
      <path
        fill="none"
        stroke="currentColor"
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth="2"
        d="M3 12L12 3l9 9M6 15l6-6l6 6M9 18l3-3l3 3"
      />
    </svg>
  ),
  Voice: () => (
    <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24">
      <path
        fill="none"
        stroke="currentColor"
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth="2"
        d="M12 2a3 3 0 0 0-3 3v6a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3M5 10v1a7 7 0 0 0 14 0v-1M12 18v4"
      />
    </svg>
  ),
};

// Built-in and example tools you register with the tool registry. Provider-neutral payloads.
export const builtinTools = [
  "get_weather",
  "web_search",
  "http_request",
  "sql_query",
  "read_file",
  "write_file",
  "run_code",
  "send_email",
  "fetch_url",
  "list_files",
  "create_event",
  "get_balance",
  "vector_search",
  "summarize",
  "translate",
  "extract_json",
  "classify",
  "transcribe",
  "synthesize",
  "call_mcp",
  "get_time",
  "geocode",
];

// Tool name -> category glyph used by the tools grid.
export const toolIconForName: Record<string, string> = {
  get_weather: "Http",
  web_search: "Search",
  http_request: "Http",
  sql_query: "Database",
  read_file: "File",
  write_file: "File",
  run_code: "Code",
  send_email: "Function",
  fetch_url: "Http",
  list_files: "File",
  create_event: "Function",
  get_balance: "Database",
  vector_search: "Search",
  summarize: "Function",
  translate: "Function",
  extract_json: "Code",
  classify: "Function",
  transcribe: "Voice",
  synthesize: "Voice",
  call_mcp: "Mcp",
  get_time: "Function",
  geocode: "Http",
};

export const categoryLabels: Record<string, string> = {
  provider: "Provider",
  tools: "Tools",
  retrieval: "Retrieval",
  modality: "Modality",
  runtime: "Runtime",
  events: "Events",
};

const _categoryColors: Record<string, string> = {
  provider: "text-violet-500/50 dark:text-violet-400/40",
  tools: "text-sky-500/50 dark:text-sky-400/40",
  retrieval: "text-emerald-500/50 dark:text-emerald-400/40",
  voice: "text-pink-500/50 dark:text-pink-400/40",
  runtime: "text-amber-500/50 dark:text-amber-400/40",
  events: "text-red-500/50 dark:text-red-400/40",
};
