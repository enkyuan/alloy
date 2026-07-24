"""`kaji gen` - generate tool stubs from an OpenAPI spec."""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path

from kaji.runtime.tools.registry import ToolRisk

HTTP_METHODS = ("get", "post", "put", "patch", "delete", "head", "options", "trace")


def to_snake_case(s: str) -> str:
    s = re.sub(r"([A-Z])", r"_\1", s)
    s = re.sub(r"[-\s]+", "_", s)
    s = re.sub(r"[^a-zA-Z0-9_]", "", s)
    s = re.sub(r"_+", "_", s)
    return s.strip("_").lower()


def extract_path_params(path: str) -> list[str]:
    return re.findall(r"\{([^}]+)\}", path)


_JSON_PRIMITIVE_TYPES = {"string", "integer", "number", "boolean"}


@dataclass
class ParamInfo:
    """A typed parameter on a parsed OpenAPI operation."""

    name: str
    location: str  # "path" | "query"
    type: str  # one of _JSON_PRIMITIVE_TYPES
    required: bool
    description: str


@dataclass
class ParsedOperation:
    operation_id: str
    fn_name: str
    method: str
    path: str
    summary: str
    tag: str | None
    path_params: list[str]
    params: list[ParamInfo]
    risk: ToolRisk


def _extract_param_type(param: dict) -> str:
    schema = param.get("schema") or {}
    typ = schema.get("type")
    if isinstance(typ, str) and typ in _JSON_PRIMITIVE_TYPES:
        return typ
    return "string"


def _parse_parameters(
    op: dict, path: str, path_item_params: list | None = None
) -> list[ParamInfo]:
    """Pull path and query parameters with their declared types out of an op.

    Body params are intentionally ignored here: we forward the whole arg dict
    as the JSON body for non-GET methods, so the model already supplies them
    via the same ``args`` object.

    OpenAPI lets the path item (``methods``) declare ``parameters`` shared by
    every operation under that path, inherited by each verb. The merge rule
    from the spec: operation-level parameters override path-item-level
    parameters on the same ``(name, in)`` key. We process path-item params
    first so the op-level pass overwrites them.
    """
    by_name: dict[str, ParamInfo] = {}
    sources: list[list] = []
    if path_item_params:
        sources.append(path_item_params)
    sources.append(op.get("parameters") or [])
    for params in sources:
        for p in params:
            if not isinstance(p, dict):
                continue
            name = p.get("name")
            loc = p.get("in")
            if not isinstance(name, str) or loc not in ("path", "query"):
                continue
            by_name[name] = ParamInfo(
                name=name,
                location=loc,
                type=_extract_param_type(p),
                required=bool(p.get("required", loc == "path")),
                description=str(p.get("description") or f"{name} {loc} param"),
            )
    # Path tokens not listed explicitly under `parameters` still need to ship.
    for raw_name in extract_path_params(path):
        if raw_name not in by_name:
            by_name[raw_name] = ParamInfo(
                name=raw_name,
                location="path",
                type="string",
                required=True,
                description=f"{raw_name} path param",
            )
    return list(by_name.values())


def parse_spec(spec: dict) -> list[ParsedOperation]:
    ops: list[ParsedOperation] = []
    for path, methods in (spec.get("paths") or {}).items():
        if not isinstance(methods, dict):
            continue
        # Path-item-level parameters apply to every operation under this path
        # (OpenAPI 3 Path Item Object); they're merged in with op-level
        # parameters winning on conflict. See `_parse_parameters`.
        path_item_params = methods.get("parameters") or []
        for method in HTTP_METHODS:
            op = methods.get(method)
            if not op or not op.get("operationId"):
                continue
            params = _parse_parameters(op, path, path_item_params)
            ops.append(
                ParsedOperation(
                    operation_id=op["operationId"],
                    fn_name=to_snake_case(op["operationId"]),
                    method=method.upper(),
                    path=path,
                    summary=op.get("summary")
                    or op.get("description")
                    or op["operationId"],
                    tag=(op.get("tags") or [None])[0],
                    path_params=[p.name for p in params if p.location == "path"],
                    params=params,
                    risk="read" if method == "get" else "write",
                )
            )
    return ops


def _infer_base_url(spec: dict) -> str:
    servers = spec.get("servers") or [{}]
    return servers[0].get("url") or "https://api.example.com"


def _infer_env_var(spec: dict) -> str:
    title = (spec.get("info") or {}).get("title") or "API"
    return to_snake_case(title).upper() + "_API_KEY"


def generate_python_file(spec: dict, ops: list[ParsedOperation], prefix: str) -> str:
    base = _infer_base_url(spec)
    env = _infer_env_var(spec)
    lines: list[str] = [
        "# Auto-generated by kaji gen. Do not edit.",
        "import os",
        "import httpx",
        "",
        f'BASE_URL = "{base}"',
        f'API_KEY = os.environ.get("{env}", "")',
        "",
        "TOOLS = [",
    ]
    for op in ops:
        name = f"{prefix}_{op.fn_name}" if prefix else op.fn_name
        prop_lines = [
            f'"{p.name}": {{"type": "{p.type}", "description": {json.dumps(p.description)}}}'
            for p in op.params
        ]
        props = ", ".join(prop_lines)
        required_names = [p.name for p in op.params if p.required]
        if required_names:
            quoted = ", ".join('"' + p + '"' for p in required_names)
            required = f', "required": [{quoted}]'
        else:
            required = ""
        lines.append(
            f"    {{\n"
            f'        "name": "{name}",\n'
            f'        "description": {json.dumps(op.summary)},\n'
            f'        "parameters": {{\n'
            f'            "type": "object",\n'
            f'            "properties": {{{props}}}{required}\n'
            f"        }},\n"
            f'        "risk": "{op.risk}",\n'
            f"    }},"
        )
    lines.append("]")
    lines.append("")
    for op in ops:
        name = f"{prefix}_{op.fn_name}" if prefix else op.fn_name
        url_path = re.sub(r"\{([^}]+)\}", r"{args['\1']}", op.path)
        query_names = [p.name for p in op.params if p.location == "query"]
        body_names = {p.name for p in op.params}
        has_body = op.method not in ("GET", "HEAD", "OPTIONS")
        if query_names:
            quoted = ", ".join('"' + q + '"' for q in query_names)
            query_kwarg = f", params={{k: args[k] for k in ({quoted},) if k in args}}"
        else:
            query_kwarg = ""
        if has_body:
            # Body excludes path + query params; remaining keys form the JSON body.
            if body_names:
                quoted_body = ", ".join('"' + n + '"' for n in body_names)
                body_kwarg = f", json={{k: v for k, v in args.items() if k not in ({quoted_body},)}}"
            else:
                body_kwarg = ", json=args"
        else:
            body_kwarg = ""
        lines.append(
            f"async def {name}(args: dict) -> dict:\n"
            f'    url = f"{{BASE_URL}}{url_path}"\n'
            f"    async with httpx.AsyncClient() as c:\n"
            f'        r = await c.request("{op.method}", url, headers={{"Authorization": f"Bearer {{API_KEY}}"}}{query_kwarg}{body_kwarg})\n'
            f"        return r.json()\n"
        )
    return "\n".join(lines)


def generate_ts_file(spec: dict, ops: list[ParsedOperation], prefix: str) -> str:
    """Identical output to apps/cli generateTsFile. Duplicated to keep Python CLI standalone."""
    base = _infer_base_url(spec)
    env = _infer_env_var(spec)
    tools_entries: list[str] = []
    for op in ops:
        name = f"{prefix}_{op.fn_name}" if prefix else op.fn_name
        prop_lines = [
            f'        {p.name}: {{ type: "{p.type}", description: {json.dumps(p.description)} }}'
            for p in op.params
        ]
        props = ",\n".join(prop_lines) or "        // no params"
        required_names = [p.name for p in op.params if p.required]
        if required_names:
            quoted_ts = ", ".join('"' + p + '"' for p in required_names)
            required = f"\n      required: [{quoted_ts}],"
        else:
            required = ""
        tag = f'\n    tags: ["{op.tag}"],' if op.tag else ""
        tools_entries.append(
            f"  {{\n"
            f'    name: "{name}",\n'
            f"    description: {json.dumps(op.summary)},\n"
            f"    parameters: {{\n"
            f'      type: "object",\n'
            f"      properties: {{\n{props}\n      }},{required}\n"
            f"    }},\n"
            f'    risk: "{op.risk}",{tag}\n'
            f"  }}"
        )
    handlers: list[str] = []
    for op in ops:
        name = f"{prefix}_{op.fn_name}" if prefix else op.fn_name
        url_path = re.sub(r"\{([^}]+)\}", r"${args.\1}", op.path)
        query_names = [p.name for p in op.params if p.location == "query"]
        body_names = {p.name for p in op.params}
        has_body = op.method not in ("GET", "HEAD", "OPTIONS")
        if query_names:
            quoted_q = ", ".join('"' + q + '"' for q in query_names)
            query_block = (
                "  for (const q of ["
                + quoted_q
                + "]) {\n"
                + "    if (q in args) url.searchParams.set(q, String((args as Record<string, unknown>)[q]));\n"
                + "  }\n"
            )
        else:
            query_block = ""
        if has_body:
            if body_names:
                quoted_b = ", ".join('"' + n + '"' for n in body_names)
                body_construct = (
                    "  const bodyKeys = new Set([" + quoted_b + "]);\n"
                    "  const body = Object.fromEntries(\n"
                    "    Object.entries(args).filter(([k]) => !bodyKeys.has(k)),\n"
                    "  );\n"
                )
                body = "\n    body: JSON.stringify(body),"
            else:
                body_construct = ""
                body = "\n    body: JSON.stringify(args),"
            ct = ', "Content-Type": "application/json"'
        else:
            body_construct = ""
            body = ""
            ct = ""
        handlers.append(
            f"export async function {name}(args: Record<string, unknown>): Promise<unknown> {{\n"
            f"  const url = new URL(`${{BASE_URL}}{url_path}`);\n"
            f"{query_block}"
            f"{body_construct}"
            f"  const r = await fetch(url.toString(), {{\n"
            f'    method: "{op.method}",\n'
            f"    headers: {{ Authorization: `Bearer ${{API_KEY}}`{ct} }},{body}\n"
            f"  }});\n"
            f"  return r.json();\n"
            f"}}"
        )
    joined_entries = ",\n".join(tools_entries)
    joined_handlers = "\n\n".join(handlers)
    return (
        "// Auto-generated by kaji gen. Do not edit.\n"
        'import type { ToolSpec } from "kaji-sdk";\n\n'
        f"// Auth: set {env} in your environment\n"
        f'const BASE_URL = "{base}";\n'
        f'const API_KEY = process.env.{env} ?? "";\n\n'
        f"export const tools: ToolSpec[] = [\n{joined_entries},\n];\n\n"
        + joined_handlers
        + "\n"
    )


def add_parser(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("gen", help="generate tool stubs from an OpenAPI spec")
    p.add_argument("--spec", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--prefix", default="")
    p.add_argument("--lang", choices=("ts", "python"), default="python")
    p.set_defaults(func=run)


def _load_spec(path: Path) -> dict:
    raw = path.read_text()
    if path.suffix.lower() == ".json":
        return json.loads(raw)
    if path.suffix.lower() in (".yaml", ".yml"):
        try:
            import yaml  # type: ignore
        except ImportError as e:
            raise SystemExit(
                "YAML specs require PyYAML. pip install pyyaml or convert to JSON."
            ) from e
        return yaml.safe_load(raw)
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        raise SystemExit(f"Failed to parse spec: {e}") from e


def run(args: argparse.Namespace) -> int:
    spec_path = Path(args.spec).resolve()
    out_dir = Path(args.out).resolve()
    if not spec_path.exists():
        print(f"Spec file not found: {spec_path}")
        return 1
    spec = _load_spec(spec_path)
    ops = parse_spec(spec)
    if not ops:
        print("No operations with operationId found in spec.")
        return 1
    out_dir.mkdir(parents=True, exist_ok=True)
    if args.lang == "python":
        out_file = out_dir / "tools.py"
        out_file.write_text(generate_python_file(spec, ops, args.prefix))
    else:
        out_file = out_dir / "index.ts"
        out_file.write_text(generate_ts_file(spec, ops, args.prefix))
    print(f"Wrote {out_file} ({len(ops)} tools)")
    return 0
