"""GitHub source provider for maintained repositories and issues."""

from __future__ import annotations

from typing import Any

import httpx


GITHUB_SEARCH_REPOS_URL = "https://api.github.com/search/repositories"
GITHUB_SEARCH_ISSUES_URL = "https://api.github.com/search/issues"


async def search_github_repositories(
    *,
    query: str,
    limit: int = 10,
    timeout: int = 12,
    token: str = "",
) -> list[dict[str, Any]]:
    safe_limit = max(1, min(int(limit), 25))
    headers = _headers(token)
    params = {"q": query, "sort": "stars", "order": "desc", "per_page": safe_limit}
    async with httpx.AsyncClient(headers=headers, timeout=timeout, follow_redirects=True) as client:
        response = await client.get(GITHUB_SEARCH_REPOS_URL, params=params)
        response.raise_for_status()
        payload = response.json()
    return parse_github_repositories(payload, query=query)


async def search_github_issues(
    *,
    query: str,
    limit: int = 10,
    timeout: int = 12,
    token: str = "",
) -> list[dict[str, Any]]:
    safe_limit = max(1, min(int(limit), 25))
    headers = _headers(token)
    params = {"q": f"{query} is:issue", "sort": "updated", "order": "desc", "per_page": safe_limit}
    async with httpx.AsyncClient(headers=headers, timeout=timeout, follow_redirects=True) as client:
        response = await client.get(GITHUB_SEARCH_ISSUES_URL, params=params)
        response.raise_for_status()
        payload = response.json()
    return parse_github_issues(payload, query=query)


def parse_github_repositories(payload: dict[str, Any], *, query: str) -> list[dict[str, Any]]:
    findings = []
    for item in payload.get("items", []) or []:
        full_name = str(item.get("full_name") or "").strip()
        url = item.get("html_url") or ""
        if not full_name or not url:
            continue
        findings.append({
            "query": query,
            "source": "github",
            "source_type": "code_repository",
            "evidence_level": "medium",
            "title": full_name,
            "url": url,
            "snippet": item.get("description") or "",
            "stars": item.get("stargazers_count", 0),
            "forks": item.get("forks_count", 0),
            "language": item.get("language") or "",
            "updated_at_source": item.get("updated_at") or "",
            "tags": ["code_repository", "implementation"],
            "accepted_for_okf": False,
        })
    return findings


def parse_github_issues(payload: dict[str, Any], *, query: str) -> list[dict[str, Any]]:
    findings = []
    for item in payload.get("items", []) or []:
        title = str(item.get("title") or "").strip()
        url = item.get("html_url") or ""
        if not title or not url:
            continue
        findings.append({
            "query": query,
            "source": "github",
            "source_type": "code_repository",
            "evidence_level": "medium",
            "title": title,
            "url": url,
            "snippet": item.get("body") or "",
            "state": item.get("state") or "",
            "comments": item.get("comments", 0),
            "updated_at_source": item.get("updated_at") or "",
            "tags": ["code_repository", "issue"],
            "accepted_for_okf": False,
        })
    return findings


def _headers(token: str) -> dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "DataclawContextResearch/0.1",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers
