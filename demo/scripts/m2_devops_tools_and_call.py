"""M2 demo/smoke-test — DevOps/code-review domain.

Same pattern as m2_register_tool_and_call.py (weather), reusing the same
demo-caller API key, but against seven DevOps tools: list open PRs, get a
diff, post a review comment, check a test run's status, create a branch,
commit a file change, and open a pull request. The write tools
(post_review_comment, commit_file_change, open_pull_request) are registered
with requires_approval=True, previewing the M8 HITL gate even though
enforcement doesn't land until then (see TECHNICAL_DESIGN.md 2.8). The three
git-write tools are groundwork for M4's auto-fix agent loop: something has to
decide *what* fix to commit (that's the LangGraph agent, M4+), but the tools
to actually commit and open a PR for review already exist here.

Prerequisites (all native/Path B — see INSTALL.md):
    uv run python demo/mock_devops_api/main.py   # demo DevOps API on :9001
    uv run python -m mcp_server.server            # MCP server on :8100
"""

import asyncio
import os
import sys
from pathlib import Path

from agenticforge_shared.db.models import AuditLog, Tool, ToolSource
from agenticforge_shared.db.session import get_session
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from sqlalchemy import select

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import KEY_FILE, ensure_api_key  # noqa: E402

MCP_SERVER_URL = os.environ.get("MCP_SERVER_URL", "http://localhost:8100/mcp")

_TOOLS = [
    {
        "tool_key": "list_open_pull_requests",
        "display_name": "List Open Pull Requests",
        "input_schema": {"type": "object", "properties": {}},
        "requires_approval": False,
    },
    {
        "tool_key": "get_pr_diff",
        "display_name": "Get Pull Request Diff",
        "input_schema": {
            "type": "object",
            "properties": {"pr_id": {"type": "string"}},
            "required": ["pr_id"],
        },
        "requires_approval": False,
    },
    {
        "tool_key": "post_review_comment",
        "display_name": "Post Review Comment",
        "input_schema": {
            "type": "object",
            "properties": {"pr_id": {"type": "string"}, "comment": {"type": "string"}},
            "required": ["pr_id", "comment"],
        },
        "requires_approval": True,
    },
    {
        "tool_key": "get_test_run_status",
        "display_name": "Get Test Run Status",
        "input_schema": {
            "type": "object",
            "properties": {"run_id": {"type": "string"}},
            "required": ["run_id"],
        },
        "requires_approval": False,
    },
    {
        "tool_key": "create_branch",
        "display_name": "Create Branch",
        "input_schema": {
            "type": "object",
            "properties": {"branch_name": {"type": "string"}, "base_branch": {"type": "string"}},
            "required": ["branch_name"],
        },
        "requires_approval": False,
    },
    {
        "tool_key": "commit_file_change",
        "display_name": "Commit File Change",
        "input_schema": {
            "type": "object",
            "properties": {
                "branch_name": {"type": "string"},
                "file_path": {"type": "string"},
                "content": {"type": "string"},
                "message": {"type": "string"},
            },
            "required": ["branch_name", "file_path", "content", "message"],
        },
        "requires_approval": True,
    },
    {
        "tool_key": "open_pull_request",
        "display_name": "Open Pull Request",
        "input_schema": {
            "type": "object",
            "properties": {
                "branch_name": {"type": "string"},
                "title": {"type": "string"},
                "description": {"type": "string"},
                "base_branch": {"type": "string"},
            },
            "required": ["branch_name", "title"],
        },
        "requires_approval": True,
    },
]


async def ensure_tool_registration(session) -> None:
    result = await session.execute(select(ToolSource).where(ToolSource.name == "demo-devops-api"))
    tool_source = result.scalar_one_or_none()
    if tool_source is None:
        tool_source = ToolSource(
            name="demo-devops-api",
            kind="manual",
            base_url_override=os.environ.get("DEVOPS_API_BASE_URL", "http://localhost:9001"),
        )
        session.add(tool_source)
        await session.flush()

    for spec in _TOOLS:
        result = await session.execute(select(Tool).where(Tool.tool_key == spec["tool_key"]))
        if result.scalar_one_or_none() is None:
            session.add(Tool(tool_source_id=tool_source.id, **spec))


async def main() -> None:
    async with get_session() as session:
        raw_key = await ensure_api_key(session)
        await ensure_tool_registration(session)
        await session.commit()

    print(f"Using API key for principal 'demo-caller' (stored at {KEY_FILE})")

    async with streamablehttp_client(
        MCP_SERVER_URL, headers={"Authorization": f"Bearer {raw_key}"}
    ) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            print("tools/list ->", [t.name for t in tools.tools])

            prs = await session.call_tool("list_open_pull_requests", {})
            print("list_open_pull_requests() ->", prs.content)

            diff = await session.call_tool("get_pr_diff", {"pr_id": "101"})
            print("get_pr_diff(101) ->", diff.content)

            comment_result = await session.call_tool(
                "post_review_comment", {"pr_id": "101", "comment": "LGTM, nice retry handling."}
            )
            print("post_review_comment(101, ...) ->", comment_result.content)

            test_status = await session.call_tool("get_test_run_status", {"run_id": "run-502"})
            print("get_test_run_status(run-502) ->", test_status.content)

            branch = await session.call_tool(
                "create_branch", {"branch_name": "fix/pagination-off-by-one", "base_branch": "main"}
            )
            print("create_branch(...) ->", branch.content)

            commit = await session.call_tool(
                "commit_file_change",
                {
                    "branch_name": "fix/pagination-off-by-one",
                    "file_path": "api/pagination.py",
                    "content": "return items[offset:offset + limit]\n",
                    "message": "Fix off-by-one in pagination slice",
                },
            )
            print("commit_file_change(...) ->", commit.content)

            pr = await session.call_tool(
                "open_pull_request",
                {
                    "branch_name": "fix/pagination-off-by-one",
                    "title": "Fix off-by-one in pagination",
                    "description": "Reverts the erroneous +1 in the pagination slice.",
                    "base_branch": "main",
                },
            )
            print("open_pull_request(...) ->", pr.content)

    async with get_session() as session:
        for tool_key in (
            "list_open_pull_requests",
            "get_pr_diff",
            "post_review_comment",
            "get_test_run_status",
            "create_branch",
            "commit_file_change",
            "open_pull_request",
        ):
            result = await session.execute(
                select(AuditLog)
                .where(AuditLog.resource_type == "tool", AuditLog.resource_id == tool_key)
                .order_by(AuditLog.created_at.desc())
                .limit(1)
            )
            entry = result.scalar_one_or_none()
            assert entry is not None, f"expected an audit_log row for {tool_key}"
            print(f"audit_log confirmed for {tool_key}: actor={entry.actor!r}")


if __name__ == "__main__":
    asyncio.run(main())
