"""Manually-registered MCP tools wrapping the demo DevOps API — the
code-review/test-automation domain example (M2). Same manual-registration
pattern as demo_weather.py; a natural OpenAPI-adapter candidate for M3 since
demo/mock_devops_api exposes a real OpenAPI schema at /openapi.json.
"""

import os

import httpx

from mcp_server.governance.audit import record_tool_call
from mcp_server.governance.auth import current_principal
from mcp_server.server import mcp

DEVOPS_API_BASE_URL = os.environ.get("DEVOPS_API_BASE_URL", "http://localhost:9001")


async def _get(path: str) -> dict | list:
    async with httpx.AsyncClient(base_url=DEVOPS_API_BASE_URL, timeout=10.0) as client:
        response = await client.get(path)
        response.raise_for_status()
        return response.json()


async def _post(path: str, json: dict) -> dict:
    async with httpx.AsyncClient(base_url=DEVOPS_API_BASE_URL, timeout=10.0) as client:
        response = await client.post(path, json=json)
        response.raise_for_status()
        return response.json()


@mcp.tool()
async def list_open_pull_requests() -> list:
    """List currently open pull requests awaiting review."""
    result = await _get("/pull-requests")
    await record_tool_call(
        tool_key="list_open_pull_requests",
        input_={},
        output={"pull_requests": result},
        actor=current_principal.get(),
    )
    return result


@mcp.tool()
async def get_pr_diff(pr_id: str) -> dict:
    """Get the unified diff for a pull request, by ID."""
    result = await _get(f"/pull-requests/{pr_id}/diff")
    await record_tool_call(
        tool_key="get_pr_diff", input_={"pr_id": pr_id}, output=result, actor=current_principal.get()
    )
    return result


@mcp.tool()
async def post_review_comment(pr_id: str, comment: str) -> dict:
    """Post a review comment on a pull request. Sensitive — writes to the PR."""
    result = await _post(f"/pull-requests/{pr_id}/comments", {"comment": comment})
    await record_tool_call(
        tool_key="post_review_comment",
        input_={"pr_id": pr_id, "comment": comment},
        output=result,
        actor=current_principal.get(),
    )
    return result


@mcp.tool()
async def get_test_run_status(run_id: str) -> dict:
    """Get the pass/fail status and duration of a CI test run, by ID."""
    result = await _get(f"/test-runs/{run_id}")
    await record_tool_call(
        tool_key="get_test_run_status",
        input_={"run_id": run_id},
        output=result,
        actor=current_principal.get(),
    )
    return result


@mcp.tool()
async def create_branch(branch_name: str, base_branch: str = "main") -> dict:
    """Create a new branch off an existing base branch."""
    result = await _post("/branches", {"branch_name": branch_name, "base_branch": base_branch})
    await record_tool_call(
        tool_key="create_branch",
        input_={"branch_name": branch_name, "base_branch": base_branch},
        output=result,
        actor=current_principal.get(),
    )
    return result


@mcp.tool()
async def commit_file_change(branch_name: str, file_path: str, content: str, message: str) -> dict:
    """Commit a file change to a branch. Sensitive — writes code content."""
    result = await _post(
        "/commits",
        {"branch_name": branch_name, "file_path": file_path, "content": content, "message": message},
    )
    await record_tool_call(
        tool_key="commit_file_change",
        input_={"branch_name": branch_name, "file_path": file_path, "message": message},
        output=result,
        actor=current_principal.get(),
    )
    return result


@mcp.tool()
async def open_pull_request(
    branch_name: str, title: str, description: str = "", base_branch: str = "main"
) -> dict:
    """Open a pull request from a branch for developer review. Sensitive — visible, notifies reviewers."""
    result = await _post(
        "/pull-requests",
        {
            "branch_name": branch_name,
            "base_branch": base_branch,
            "title": title,
            "description": description,
        },
    )
    await record_tool_call(
        tool_key="open_pull_request",
        input_={"branch_name": branch_name, "title": title, "base_branch": base_branch},
        output=result,
        actor=current_principal.get(),
    )
    return result
