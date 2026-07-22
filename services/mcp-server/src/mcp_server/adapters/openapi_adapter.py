"""OpenAPI-to-MCP adapter (M3).

Given an OpenAPI 3.x spec, generates one MCP tool per operation — the
mechanism behind "hook up any set of APIs by pointing at their OpenAPI spec"
rather than hand-writing a wrapper function per endpoint (M2's manual path,
which remains available for APIs without a spec or that need custom logic).

Scope, deliberately kept simple ("built in-house, dependency-light" per
TECHNICAL_DESIGN.md 2.5): flat path/query parameters and a flat (single
level, non-nested) JSON request body. Covers the demo APIs and most simple
internal-service specs. Not handled: nested objects/arrays in the body,
oneOf/anyOf, non-JSON bodies, enums beyond simple string/number/bool/int
scalars. A real production adapter would lean on a JSON-schema library for
those cases; this one intentionally doesn't pull one in yet.

Registration is boot-time, not hot-reload: mcp-server reads ToolSource rows
(kind="openapi") once at startup (see server.py) and calls
register_tools_from_openapi() for each. Adding/changing an OpenAPI ToolSource
means restarting mcp-server to pick it up — a live-reload admin endpoint is a
reasonable future enhancement, not built here to keep M3 scoped to the
adapter mechanism itself.
"""

import re

import httpx

from mcp_server.governance.audit import record_tool_call
from mcp_server.governance.auth import current_principal
from mcp_server.server import mcp

_PY_TYPE = {"integer": "int", "number": "float", "boolean": "bool"}  # default: str


def _sanitize(name: str) -> str:
    return re.sub(r"\W", "_", name)


def _resolve_schema(schema: dict, spec: dict) -> dict:
    """Resolves a single-level "$ref": "#/components/schemas/X" pointer.
    FastAPI (and most OpenAPI 3.x generators) emit request bodies as a $ref
    into components.schemas rather than an inline schema.
    """
    if "$ref" not in schema:
        return schema
    node = spec
    for part in schema["$ref"].lstrip("#/").split("/"):
        node = node[part]
    return node


def _build_auth_headers(auth_config: dict | None) -> dict:
    if not auth_config:
        return {}
    auth_type = auth_config.get("type")
    if auth_type == "bearer":
        return {"Authorization": f"Bearer {auth_config['token']}"}
    if auth_type == "header":
        return {auth_config["name"]: auth_config["value"]}
    return {}


async def fetch_openapi_spec(spec_url: str) -> dict:
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(spec_url)
        response.raise_for_status()
        return response.json()


async def _execute_operation(
    method: str,
    path_template: str,
    base_url: str,
    auth_config: dict | None,
    path_values: dict,
    query_values: dict,
    body_value: dict | None,
) -> dict:
    url_path = path_template
    for key, value in path_values.items():
        url_path = url_path.replace("{" + key + "}", str(value))

    query_values = {k: v for k, v in query_values.items() if v is not None}
    if body_value is not None:
        body_value = {k: v for k, v in body_value.items() if v is not None}

    async with httpx.AsyncClient(base_url=base_url, timeout=10.0) as client:
        response = await client.request(
            method.upper(),
            url_path,
            params=query_values or None,
            json=body_value,
            headers=_build_auth_headers(auth_config) or None,
        )
        response.raise_for_status()
        return response.json()


async def _record(tool_key: str, input_: dict, output: dict) -> None:
    await record_tool_call(tool_key=tool_key, input_=input_, output=output, actor=current_principal.get())


def _param_specs(op: dict, shared_params: list[dict], location: str) -> list[dict]:
    specs = []
    for p in shared_params + op.get("parameters", []):
        if p.get("in") != location:
            continue
        specs.append(
            {
                "raw_name": p["name"],
                "name": _sanitize(p["name"]),
                "required": p.get("required", False),
                "type": p.get("schema", {}).get("type", "string"),
            }
        )
    return specs


def _response_return_type(op: dict, spec: dict) -> str:
    """Most operations return a JSON object, but some (e.g. a "list X"
    endpoint) return a JSON array — get this right so the generated
    function's return annotation matches what it actually returns at
    runtime, not just a hardcoded guess.
    """
    responses = op.get("responses", {})
    ok_response = responses.get("200") or responses.get("201") or {}
    schema = ok_response.get("content", {}).get("application/json", {}).get("schema", {})
    schema = _resolve_schema(schema, spec)
    return "list" if schema.get("type") == "array" else "dict"


def _body_field_specs(op: dict, spec: dict) -> list[dict]:
    request_body = op.get("requestBody")
    if not request_body:
        return []
    json_schema = request_body.get("content", {}).get("application/json", {}).get("schema", {})
    json_schema = _resolve_schema(json_schema, spec)
    required = set(json_schema.get("required", []))
    return [
        {
            "raw_name": field_name,
            "name": _sanitize(field_name),
            "required": field_name in required,
            "type": field_schema.get("type", "string"),
        }
        for field_name, field_schema in json_schema.get("properties", {}).items()
    ]


def _build_tool_function(
    *,
    operation_id: str,
    method: str,
    path_template: str,
    base_url: str,
    auth_config: dict | None,
    path_params: list[dict],
    query_params: list[dict],
    body_fields: list[dict],
    return_type: str = "dict",
):
    """Synthesizes a real async function with a genuine parameter signature
    (via exec) so FastMCP's normal type-hint-based schema introspection works
    on it exactly as it would on a hand-written tool — no reliance on any
    lower-level/undocumented schema-override API.
    """
    func_name = _sanitize(operation_id) or "generated_tool"
    all_params = path_params + query_params + body_fields
    # Required params must precede optional ones in a Python signature.
    ordered = sorted(all_params, key=lambda p: not p["required"])

    sig_parts = []
    for p in ordered:
        py_type = _PY_TYPE.get(p["type"], "str")
        sig_parts.append(f"{p['name']}: {py_type}" if p["required"] else f"{p['name']}: {py_type} | None = None")
    signature = ", ".join(sig_parts)

    path_dict = "{" + ", ".join(f'"{p["raw_name"]}": {p["name"]}' for p in path_params) + "}"
    query_dict = "{" + ", ".join(f'"{p["raw_name"]}": {p["name"]}' for p in query_params) + "}"
    body_dict = (
        "{" + ", ".join(f'"{p["raw_name"]}": {p["name"]}' for p in body_fields) + "}" if body_fields else "None"
    )
    all_values_dict = (
        "{" + ", ".join(f'"{p["raw_name"]}": {p["name"]}' for p in all_params) + "}"
    )

    source = (
        f"async def {func_name}({signature}) -> {return_type}:\n"
        f"    result = await _execute_operation(\n"
        f"        {method!r}, {path_template!r}, _base_url, _auth_config,\n"
        f"        {path_dict}, {query_dict}, {body_dict},\n"
        f"    )\n"
        f"    await _record({operation_id!r}, {all_values_dict}, result)\n"
        f"    return result\n"
    )

    namespace = {
        "_execute_operation": _execute_operation,
        "_record": _record,
        "_base_url": base_url,
        "_auth_config": auth_config,
    }
    exec(compile(source, f"<openapi_adapter:{operation_id}>", "exec"), namespace)  # noqa: S102
    return namespace[func_name]


def register_tools_from_openapi(
    spec: dict,
    base_url: str,
    auth_config: dict | None = None,
    include_operations: list[str] | None = None,
) -> list[str]:
    """Generates and registers one MCP tool per operation in `spec`. Returns
    the list of registered tool (operation) names.
    """
    auth_config = auth_config or {}
    registered: list[str] = []

    for path_template, path_item in spec.get("paths", {}).items():
        shared_params = path_item.get("parameters", [])
        for method, op in path_item.items():
            if method.lower() not in ("get", "post", "put", "patch", "delete"):
                continue

            operation_id = op.get("operationId") or f"{method}_{_sanitize(path_template)}"
            if include_operations and operation_id not in include_operations:
                continue

            path_params = _param_specs(op, shared_params, "path")
            query_params = _param_specs(op, shared_params, "query")
            body_fields = _body_field_specs(op, spec)
            return_type = _response_return_type(op, spec)

            fn = _build_tool_function(
                operation_id=operation_id,
                method=method,
                path_template=path_template,
                base_url=base_url,
                auth_config=auth_config,
                path_params=path_params,
                query_params=query_params,
                body_fields=body_fields,
                return_type=return_type,
            )
            description = op.get("summary") or op.get("description") or f"{method.upper()} {path_template}"
            mcp.add_tool(fn, name=operation_id, description=f"[auto-generated] {description}")
            registered.append(operation_id)

    return registered
