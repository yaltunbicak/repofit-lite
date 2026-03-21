"""GitLab REST API client — corrected endpoints and rate limiting."""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import quote_plus

import httpx

from repofit.models import RepoCandidate
from repofit.utils import RateLimiterRegistry, api_retry

logger = logging.getLogger("repofit")


class GitLabClient:
    """Async GitLab API client with rate limiting."""

    def __init__(self, token: str | None, base_url: str, rate_limiter: RateLimiterRegistry) -> None:
        self.token = token
        self.base_url = base_url.rstrip("/")
        self.limiter = rate_limiter
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> GitLabClient:
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["PRIVATE-TOKEN"] = self.token
        self._client = httpx.AsyncClient(
            base_url=f"{self.base_url}/api/v4",
            timeout=30.0,
            headers=headers,
            limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
        )
        return self

    async def __aexit__(self, *args: object) -> None:
        if self._client:
            await self._client.aclose()

    @api_retry
    async def _get(self, path: str, bucket: str = "gitlab_api", **kwargs: Any) -> httpx.Response:
        await self.limiter.acquire(bucket)
        r = await self._client.get(path, **kwargs)
        r.raise_for_status()
        return r

    async def _get_json(self, path: str, bucket: str = "gitlab_api", **kwargs: Any) -> Any:
        r = await self._get(path, bucket=bucket, **kwargs)
        return r.json()

    async def _get_safe(self, path: str, default: Any = None, **kwargs: Any) -> Any:
        try:
            return await self._get_json(path, **kwargs)
        except Exception:
            return default

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    async def search_projects(
        self, query: str, sort: str = "stars", max_results: int = 10,
    ) -> list[RepoCandidate]:
        try:
            r = await self._get(
                "/search",
                bucket="gitlab_search",
                params={"scope": "projects", "search": query, "per_page": min(max_results, 20)},
            )
        except httpx.HTTPStatusError:
            logger.warning("GitLab search failed for: %s", query)
            return []

        items = r.json()
        candidates = []
        for rank, item in enumerate(items[:max_results], 1):
            candidates.append(RepoCandidate(
                source="gitlab",
                full_name=item.get("path_with_namespace", ""),
                url=item.get("web_url", ""),
                description=item.get("description"),
                stars=item.get("star_count"),
                forks=item.get("forks_count"),
                language=None,
                topics=item.get("topics", []) or item.get("tag_list", []),
                updated_at=item.get("last_activity_at"),
                search_query=query,
                search_rank=rank,
            ))
        logger.debug("GitLab search '%s' returned %d results", query, len(candidates))
        return candidates

    # ------------------------------------------------------------------
    # Enrichment endpoints
    # ------------------------------------------------------------------

    async def get_project_detail(self, project_path: str) -> dict:
        encoded = quote_plus(project_path)
        return await self._get_json(f"/projects/{encoded}", params={"license": "true", "statistics": "true"})

    async def get_languages(self, project_path: str) -> dict:
        encoded = quote_plus(project_path)
        return await self._get_json(f"/projects/{encoded}/languages")

    async def get_contributors_count(self, project_path: str) -> int:
        """Get contributor count using /repository/contributors + x-total header."""
        encoded = quote_plus(project_path)
        try:
            r = await self._get(
                f"/projects/{encoded}/repository/contributors",
                params={"per_page": 1},
            )
            total = r.headers.get("x-total")
            if total:
                return int(total)
            return len(r.json()) if isinstance(r.json(), list) else 0
        except (httpx.HTTPStatusError, ValueError):
            return 0

    async def get_releases(self, project_path: str, per_page: int = 10) -> list[dict]:
        encoded = quote_plus(project_path)
        return await self._get_safe(f"/projects/{encoded}/releases", default=[], params={"per_page": per_page})

    async def get_readme(self, project_path: str) -> str | None:
        """Get README using ref=HEAD (auto-resolves default branch)."""
        encoded = quote_plus(project_path)
        try:
            r = await self._get(
                f"/projects/{encoded}/repository/files/README.md/raw",
                bucket="gitlab_api",
                params={"ref": "HEAD"},
            )
            return r.text
        except httpx.HTTPStatusError:
            return None

    async def get_repository_tree(self, project_path: str) -> list[dict]:
        encoded = quote_plus(project_path)
        return await self._get_safe(f"/projects/{encoded}/repository/tree", default=[], params={"per_page": 100})

    async def get_commit_count_90d(self, project_path: str) -> int:
        """Get commit count in last 90 days by paginating commits API."""
        from datetime import datetime, timedelta, timezone
        encoded = quote_plus(project_path)
        since = (datetime.now(timezone.utc) - timedelta(days=90)).isoformat()
        total = 0
        for page in range(1, 6):  # Max 5 pages = 500 commits
            try:
                data = await self._get_json(
                    f"/projects/{encoded}/repository/commits",
                    params={"since": since, "per_page": 100, "page": page},
                )
                if not data or not isinstance(data, list):
                    break
                total += len(data)
                if len(data) < 100:
                    break
            except Exception:
                break
        return total
