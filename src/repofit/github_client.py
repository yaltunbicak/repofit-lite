"""GitHub REST API client — centralized request architecture."""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

import httpx

from repofit.models import RepoCandidate
from repofit.utils import RateLimiterRegistry, TokenRotator, api_retry

logger = logging.getLogger("repofit")

GITHUB_API = "https://api.github.com"


class GitHubClient:
    """Async GitHub API client with token rotation and rate limiting."""

    def __init__(self, tokens: list[str], rate_limiter: RateLimiterRegistry) -> None:
        self.rotator = TokenRotator(tokens)
        self.limiter = rate_limiter
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> GitHubClient:
        self._client = httpx.AsyncClient(
            base_url=GITHUB_API,
            timeout=30.0,
            headers=self._headers(),
            limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
        )
        return self

    async def __aexit__(self, *args: object) -> None:
        if self._client:
            await self._client.aclose()

    def _headers(self) -> dict[str, str]:
        return {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {self.rotator.current()}",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    def _rotate_token(self) -> None:
        if self.rotator.count > 1:
            new_token = self.rotator.next()
            if self._client:
                self._client.headers["Authorization"] = f"Bearer {new_token}"
            logger.debug("Rotated to next GitHub token")

    # ------------------------------------------------------------------
    # Transport layer — single entry point for ALL HTTP requests
    # ------------------------------------------------------------------

    @api_retry
    async def _request(
        self, method: str, path: str, bucket: str = "github_core", **kwargs: Any,
    ) -> httpx.Response:
        """Centralized request with rate limiting, retry, and token rotation."""
        await self.limiter.acquire(bucket)
        r = await self._client.request(method, path, **kwargs)
        if r.status_code in (403, 429):
            self._rotate_token()
            r.raise_for_status()  # tenacity will retry
        r.raise_for_status()
        return r

    async def _get(self, path: str, bucket: str = "github_core", **kwargs: Any) -> httpx.Response:
        return await self._request("GET", path, bucket=bucket, **kwargs)

    async def _get_json(self, path: str, bucket: str = "github_core", **kwargs: Any) -> Any:
        r = await self._get(path, bucket=bucket, **kwargs)
        return r.json()

    async def _get_safe(self, path: str, default: Any = None, **kwargs: Any) -> Any:
        """GET that returns default on any error — for optional enrichment calls."""
        try:
            return await self._get_json(path, **kwargs)
        except Exception:
            return default

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    async def search_repos(
        self, query: str, language: str | None = None, sort: str = "stars", max_results: int = 10,
    ) -> list[RepoCandidate]:
        q = query
        if language:
            q += f" language:{language}"
        try:
            r = await self._get(
                "/search/repositories",
                bucket="github_search",
                params={"q": q, "sort": sort, "per_page": min(max_results, 30), "page": 1},
            )
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 422:
                logger.warning("GitHub search rejected query: %s", query)
                return []
            raise

        items = r.json().get("items", [])
        candidates = []
        for rank, item in enumerate(items[:max_results], 1):
            candidates.append(RepoCandidate(
                source="github",
                full_name=item["full_name"],
                url=item["html_url"],
                description=item.get("description"),
                stars=item.get("stargazers_count"),
                forks=item.get("forks_count"),
                language=item.get("language"),
                topics=item.get("topics", []),
                updated_at=item.get("updated_at"),
                search_query=query,
                search_rank=rank,
            ))
        logger.debug("GitHub search '%s' returned %d results", query, len(candidates))
        return candidates

    # ------------------------------------------------------------------
    # Enrichment endpoints
    # ------------------------------------------------------------------

    async def get_repo_detail(self, owner: str, repo: str) -> dict:
        return await self._get_json(f"/repos/{owner}/{repo}")

    async def get_languages(self, owner: str, repo: str) -> dict[str, int]:
        return await self._get_json(f"/repos/{owner}/{repo}/languages")

    async def get_contributors_count(self, owner: str, repo: str) -> int:
        try:
            r = await self._get(
                f"/repos/{owner}/{repo}/contributors",
                params={"per_page": 1, "anon": "true"},
            )
            link = r.headers.get("Link", "")
            if 'rel="last"' in link:
                match = re.search(r'page=(\d+)>; rel="last"', link)
                if match:
                    return int(match.group(1))
            return len(r.json())
        except httpx.HTTPStatusError:
            return 0

    async def get_releases(self, owner: str, repo: str, per_page: int = 10) -> list[dict]:
        return await self._get_json(f"/repos/{owner}/{repo}/releases", params={"per_page": per_page})

    async def get_readme(self, owner: str, repo: str) -> str | None:
        try:
            r = await self._get(
                f"/repos/{owner}/{repo}/readme",
                headers={"Accept": "application/vnd.github.raw"},
            )
            return r.text
        except httpx.HTTPStatusError:
            return None

    async def get_community_profile(self, owner: str, repo: str) -> dict:
        return await self._get_safe(f"/repos/{owner}/{repo}/community/profile", default={})

    async def get_commit_activity(self, owner: str, repo: str) -> list[dict]:
        """Get weekly commit activity. Retries on 202 (computing)."""
        for attempt in range(3):
            try:
                r = await self._get(f"/repos/{owner}/{repo}/stats/commit_activity")
                data = r.json()
                return data if isinstance(data, list) else []
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 202:
                    logger.debug("Stats computing for %s/%s, retry %d", owner, repo, attempt + 1)
                    await asyncio.sleep(2)
                    continue
                return []
        return []

    async def get_contents_root(self, owner: str, repo: str) -> list[dict]:
        return await self._get_safe(f"/repos/{owner}/{repo}/contents/", default=[])

    async def get_workflows_exist(self, owner: str, repo: str) -> bool:
        """Check if .github/workflows directory exists (CI detection)."""
        try:
            await self._get(f"/repos/{owner}/{repo}/contents/.github/workflows")
            return True
        except httpx.HTTPStatusError:
            return False
