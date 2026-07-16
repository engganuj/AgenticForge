"""Tiny demo REST API standing in for a code-hosting/CI platform (e.g. GitHub
+ a test runner), used as the target for the DevOps/code-review MCP tools.
Mirrors the shape of a real OpenAPI-described API so it's also a candidate
for the M3 OpenAPI-to-MCP adapter later.
"""

import secrets

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI(title="Demo DevOps API", version="1.0.0")

_PULL_REQUESTS = {
    "101": {
        "id": "101",
        "title": "Add retry logic to ingestion worker",
        "author": "alice",
        "status": "open",
        "diff": (
            "--- a/ingestion/retry.py\n"
            "+++ b/ingestion/retry.py\n"
            "@@ -1,3 +1,8 @@\n"
            "+import backoff\n"
            "+\n"
            "+@backoff.on_exception(backoff.expo, ConnectionError, max_tries=3)\n"
            " def fetch(source):\n"
            "     ...\n"
        ),
    },
    "102": {
        "id": "102",
        "title": "Fix off-by-one in pagination",
        "author": "bob",
        "status": "open",
        "diff": (
            "--- a/api/pagination.py\n"
            "+++ b/api/pagination.py\n"
            "@@ -10,7 +10,7 @@\n"
            "-    return items[offset:offset + limit]\n"
            "+    return items[offset:offset + limit + 1]\n"
        ),
    },
}

_TEST_RUNS = {
    "run-501": {"run_id": "run-501", "status": "passed", "passed": 214, "failed": 0, "duration_s": 87.4},
    "run-502": {"run_id": "run-502", "status": "failed", "passed": 210, "failed": 4, "duration_s": 92.1},
}

_COMMENTS: dict[str, list[dict]] = {}
_BRANCHES: dict[str, dict] = {"main": {"branch_name": "main", "base_branch": None, "sha": "0" * 40}}
_COMMITS: list[dict] = []
_next_pr_id = max((int(pr_id) for pr_id in _PULL_REQUESTS), default=100) + 1


class ReviewComment(BaseModel):
    comment: str


class CreateBranchRequest(BaseModel):
    branch_name: str
    base_branch: str = "main"


class CommitFileChangeRequest(BaseModel):
    branch_name: str
    file_path: str
    content: str
    message: str


class OpenPullRequestRequest(BaseModel):
    branch_name: str
    base_branch: str = "main"
    title: str
    description: str = ""


@app.get("/pull-requests", operation_id="listOpenPullRequests")
def list_open_pull_requests() -> list[dict]:
    return [pr for pr in _PULL_REQUESTS.values() if pr["status"] == "open"]


@app.get("/pull-requests/{pr_id}/diff", operation_id="getPullRequestDiff")
def get_pr_diff(pr_id: str) -> dict:
    pr = _PULL_REQUESTS.get(pr_id)
    if pr is None:
        raise HTTPException(status_code=404, detail=f"no such pull request: {pr_id}")
    return {"pr_id": pr_id, "diff": pr["diff"]}


@app.post("/pull-requests/{pr_id}/comments", operation_id="postReviewComment")
def post_review_comment(pr_id: str, body: ReviewComment) -> dict:
    if pr_id not in _PULL_REQUESTS:
        raise HTTPException(status_code=404, detail=f"no such pull request: {pr_id}")
    _COMMENTS.setdefault(pr_id, []).append({"comment": body.comment})
    return {"pr_id": pr_id, "status": "comment_posted", "comment": body.comment}


@app.get("/test-runs/{run_id}", operation_id="getTestRunStatus")
def get_test_run_status(run_id: str) -> dict:
    run = _TEST_RUNS.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"no such test run: {run_id}")
    return run


@app.post("/branches", operation_id="createBranch")
def create_branch(body: CreateBranchRequest) -> dict:
    if body.branch_name in _BRANCHES:
        raise HTTPException(status_code=409, detail=f"branch already exists: {body.branch_name}")
    if body.base_branch not in _BRANCHES:
        raise HTTPException(status_code=404, detail=f"no such base branch: {body.base_branch}")
    branch = {
        "branch_name": body.branch_name,
        "base_branch": body.base_branch,
        "sha": secrets.token_hex(20),
    }
    _BRANCHES[body.branch_name] = branch
    return branch


@app.post("/commits", operation_id="commitFileChange")
def commit_file_change(body: CommitFileChangeRequest) -> dict:
    if body.branch_name not in _BRANCHES:
        raise HTTPException(status_code=404, detail=f"no such branch: {body.branch_name}")
    commit = {
        "commit_sha": secrets.token_hex(20),
        "branch_name": body.branch_name,
        "file_path": body.file_path,
        "message": body.message,
    }
    _COMMITS.append(commit)
    _BRANCHES[body.branch_name]["sha"] = commit["commit_sha"]
    return commit


@app.post("/pull-requests", operation_id="openPullRequest")
def open_pull_request(body: OpenPullRequestRequest) -> dict:
    global _next_pr_id
    if body.branch_name not in _BRANCHES:
        raise HTTPException(status_code=404, detail=f"no such branch: {body.branch_name}")
    branch_commits = [c for c in _COMMITS if c["branch_name"] == body.branch_name]
    diff = "".join(
        f"--- a/{c['file_path']}\n+++ b/{c['file_path']}\n# {c['message']}\n" for c in branch_commits
    ) or "# no commits on this branch yet\n"
    pr_id = str(_next_pr_id)
    _next_pr_id += 1
    pr = {
        "id": pr_id,
        "title": body.title,
        "author": "agenticforge-bot",
        "status": "open",
        "branch_name": body.branch_name,
        "base_branch": body.base_branch,
        "description": body.description,
        "diff": diff,
    }
    _PULL_REQUESTS[pr_id] = pr
    return pr


if __name__ == "__main__":
    import os

    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("DEVOPS_API_PORT", "9001")))
