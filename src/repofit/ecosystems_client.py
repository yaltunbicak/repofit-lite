"""ecosyste.ms API client."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from repofit.models import RepoCandidate
from repofit.utils import RateLimiterRegistry, api_retry, extract_owner_repo

logger = logging.getLogger("repofit")

ECOSYSTEMS_API = "https://repos.ecosyste.ms/api/v1"


class EcosystemsClient:
    """Async ecosyste.ms API client."""

    def __init__(self, email: str | None, rate_limiter: RateLimiterRegistry) -> None:
        self.email = email
        self.limiter = rate_limiter
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> EcosystemsClient:
        headers = {"Accept": "application/json"}
        if self.email:
            headers["User-Agent"] = f"RepoFit/0.1 ({self.email})"
        self._client = httpx.AsyncClient(
            base_url=ECOSYSTEMS_API,
            timeout=30.0,
            headers=headers,
            limits=httpx.Limits(max_connections=5),
        )
        return self

    async def __aexit__(self, *args: object) -> None:
        if self._client:
            await self._client.aclose()

    @api_retry
    async def _get_json(self, path: str, params: dict | None = None) -> Any:
        await self.limiter.acquire("ecosystems")
        r = await self._client.get(path, params=params)
        r.raise_for_status()
        return r.json()

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    async def search_repos(self, query: str, max_results: int = 10) -> list[RepoCandidate]:
        try:
            await self.limiter.acquire("ecosystems")
            r = await self._client.get(
                "/repositories/search",
                params={"q": query, "per_page": min(max_results, 30)},
            )
            if r.status_code != 200:
                logger.warning("ecosyste.ms search failed (%d) for: %s", r.status_code, query)
                return []

            items = r.json()
            if not isinstance(items, list):
                items = items.get("items", []) if isinstance(items, dict) else []

            candidates = []
            for rank, item in enumerate(items[:max_results], 1):
                url = item.get("url", "") or item.get("repository_url", "")
                # Derive full_name from URL
                full_name = item.get("full_name", "")
                if not full_name and url:
                    parsed = extract_owner_repo(url)
                    full_name = f"{parsed[0]}/{parsed[1]}" if parsed else ""

                source = "github" if "github.com" in url else "gitlab" if "gitlab" in url else "ecosystems"
                candidates.append(RepoCandidate(
                    source=source,
                    full_name=full_name,
                    url=url,
                    description=item.get("description"),
                    stars=item.get("stargazers_count") or item.get("stars"),
                    forks=item.get("forks_count") or item.get("forks"),
                    language=item.get("language"),
                    topics=item.get("topics", []) or [],
                    updated_at=item.get("updated_at"),
                    search_query=query,
                    search_rank=rank,
                ))
            logger.debug("ecosyste.ms search '%s' returned %d results", query, len(candidates))
            return candidates
        except httpx.HTTPStatusError as e:
            logger.warning("ecosyste.ms search error for '%s': %s", query, e)
            return []
        except Exception as e:
            logger.warning("ecosyste.ms search error for '%s': %s", query, e)
            return []

    # ------------------------------------------------------------------
    # Enrichment
    # ------------------------------------------------------------------

    async def get_repo_detail(self, repo_url: str) -> dict | None:
        """Get repo detail including dependent counts and downloads."""
        try:
            data = await self._get_json("/repositories/lookup", {"url": repo_url})
            return data
        except Exception as e:
            logger.debug("ecosyste.ms detail lookup failed for %s: %s", repo_url, e)
            return None
