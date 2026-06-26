"""GitHub integration -- read repos, issues, PRs via a personal access token.

Installed by `kaji add github`. Edit freely; this file is yours to own
once it's copied into your project. The version inside the SDK is the
template; the version in your repo is the source of truth.

Auth: set ``GITHUB_TOKEN`` in the environment. Create one at
https://github.com/settings/tokens with at least the ``repo`` scope (or
``read:org`` for private orgs). The integration reads the env var at
construction time; raise loudly if it's unset rather than failing at
the first request.
"""

from __future__ import annotations

import os
from typing import Any, Optional

import httpx
from pydantic import BaseModel, Field

import kaji


GITHUB_API = "https://api.github.com"


class GetRepoArgs(BaseModel):
    owner: str = Field(description="The GitHub user or org that owns the repo.")
    repo: str = Field(description="The repository name.")


class ListIssuesArgs(BaseModel):
    owner: str = Field(description="The GitHub user or org.")
    repo: str = Field(description="The repository name.")
    state: str = Field(
        default="open",
        description="Issue state: 'open', 'closed', or 'all'.",
    )
    per_page: int = Field(
        default=20,
        description="Number of issues to return (1-100).",
    )


class GetPullRequestArgs(BaseModel):
    owner: str
    repo: str
    number: int = Field(description="The PR number.")


class SearchReposArgs(BaseModel):
    query: str = Field(description="GitHub repository search query.")
    per_page: int = Field(default=10)


class GitHub(kaji.Integration):
    """Read-only GitHub tools backed by a personal access token."""

    namespace = "github"

    def __init__(self, token: Optional[str] = None) -> None:
        resolved = token or os.environ.get("GITHUB_TOKEN")
        if not resolved:
            raise RuntimeError(
                "GitHub integration requires GITHUB_TOKEN to be set. "
                "Create one at https://github.com/settings/tokens."
            )
        self._token = resolved

    async def _get(self, path: str, params: Optional[dict] = None) -> Any:
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.get(
                f"{GITHUB_API}{path}", headers=headers, params=params
            )
            resp.raise_for_status()
            return resp.json()

    @kaji.tool(
        description="Fetch a repository's metadata: stars, default branch, description, etc.",
        parameters=GetRepoArgs,
        risk="read",
    )
    async def get_repo(self, ctx: kaji.ToolContext, args: dict) -> dict:
        data = await self._get(f"/repos/{args['owner']}/{args['repo']}")
        return {
            "full_name": data.get("full_name"),
            "description": data.get("description"),
            "stargazers_count": data.get("stargazers_count"),
            "default_branch": data.get("default_branch"),
            "open_issues_count": data.get("open_issues_count"),
            "language": data.get("language"),
            "html_url": data.get("html_url"),
        }

    @kaji.tool(
        description="List issues for a repository. State filters to open/closed/all.",
        parameters=ListIssuesArgs,
        risk="read",
    )
    async def list_issues(self, ctx: kaji.ToolContext, args: dict) -> dict:
        params = {
            "state": args.get("state", "open"),
            "per_page": min(int(args.get("per_page", 20)), 100),
        }
        data = await self._get(
            f"/repos/{args['owner']}/{args['repo']}/issues", params=params
        )
        # Filter out pull requests; GitHub's /issues endpoint includes them.
        issues = [i for i in data if "pull_request" not in i]
        return {
            "issues": [
                {
                    "number": i.get("number"),
                    "title": i.get("title"),
                    "state": i.get("state"),
                    "user": (i.get("user") or {}).get("login"),
                    "html_url": i.get("html_url"),
                }
                for i in issues
            ]
        }

    @kaji.tool(
        description="Fetch a pull request by number.",
        parameters=GetPullRequestArgs,
        risk="read",
    )
    async def get_pull_request(self, ctx: kaji.ToolContext, args: dict) -> dict:
        data = await self._get(
            f"/repos/{args['owner']}/{args['repo']}/pulls/{int(args['number'])}"
        )
        return {
            "number": data.get("number"),
            "title": data.get("title"),
            "state": data.get("state"),
            "merged": data.get("merged"),
            "draft": data.get("draft"),
            "user": (data.get("user") or {}).get("login"),
            "body": data.get("body"),
            "additions": data.get("additions"),
            "deletions": data.get("deletions"),
            "changed_files": data.get("changed_files"),
            "html_url": data.get("html_url"),
        }

    @kaji.tool(
        description="Search public repositories. Uses GitHub's repo search.",
        parameters=SearchReposArgs,
        risk="read",
    )
    async def search_repos(self, ctx: kaji.ToolContext, args: dict) -> dict:
        params = {
            "q": args["query"],
            "per_page": min(int(args.get("per_page", 10)), 100),
        }
        data = await self._get("/search/repositories", params=params)
        return {
            "total_count": data.get("total_count"),
            "items": [
                {
                    "full_name": r.get("full_name"),
                    "description": r.get("description"),
                    "stargazers_count": r.get("stargazers_count"),
                    "html_url": r.get("html_url"),
                }
                for r in (data.get("items") or [])
            ],
        }
